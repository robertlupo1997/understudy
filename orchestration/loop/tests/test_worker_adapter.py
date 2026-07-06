import textwrap
import pytest
from orchestration.loop import worker_adapter as wa
from orchestration.loop import queue as q
from orchestration.loop import config as cfg
from orchestration.loop.tests.conftest import write_config_yaml


def _task(tmp_path, target='[add.py]', complexity="simple"):
    p = tmp_path / "t.md"
    p.write_text(textwrap.dedent(f"""\
        ---
        id: t
        title: "Add"
        complexity: {complexity}
        check_author: claude
        check_cmd: "true"
        target_files: {target}
        status: queued
        context: |
          use stdlib only
        ---
        Implement add(a, b).
        """))
    return q.parse_task(str(p))


def test_build_prompt_includes_title_prose_context(tmp_path):
    t = _task(tmp_path)
    prompt = wa.build_prompt(t)
    assert "Add" in prompt
    assert "Implement add(a, b)." in prompt
    assert "use stdlib only" in prompt


def test_rejects_multi_file(tmp_path):
    t = _task(tmp_path, target='[a.py, b.py]')
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", tmp_path)))
    with pytest.raises(wa.WorkerAdapterError):
        wa.run_worker(t, str(tmp_path), c)


def test_run_worker_invokes_worker_and_maps_result(tmp_path, monkeypatch):
    t = _task(tmp_path, complexity="complex")
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", tmp_path)))
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = "files changed: /x\nwhat was done: wrote 2 lines"
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(wa.subprocess, "run", fake_run)
    r = wa.run_worker(t, str(tmp_path), c)
    assert r.ok and r.exit_code == 0
    assert r.model == "ornith35b"                      # complex → complex model
    assert "files changed" in r.summary
    assert "--allowed-dir" in captured["cmd"]
    assert str(tmp_path) in captured["cmd"]            # confinement dir passed
    assert "--model" in captured["cmd"] and "ornith35b" in captured["cmd"]
