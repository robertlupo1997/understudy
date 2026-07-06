import shutil
import textwrap
import pytest
from orchestration.loop import gate
from orchestration.loop import queue as q
from orchestration.loop import config as cfg
from orchestration.loop.tests.conftest import write_config_yaml

pytestmark = pytest.mark.sandbox            # spawns bwrap; excluded from the no-regression leg
needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap required")


def _task(tmp_path, author="claude", check="python3 -m pytest test_add.py -q"):
    p = tmp_path / "t.md"
    p.write_text(textwrap.dedent(f"""\
        ---
        id: t
        title: "Add"
        complexity: simple
        check_author: {author}
        check_cmd: "{check}"
        target_files: [add.py]
        status: queued
        context: ""
        ---
        body
        """))
    return q.parse_task(str(p))


def _config(tmp_path):
    return cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", tmp_path)))


def test_build_sandbox_argv_substitutes(tmp_path):
    c = _config(tmp_path)
    argv = gate.build_sandbox_argv(c.gate.sandbox, "/wt", "/home/u")
    assert "bwrap" == argv[0]
    assert "/wt" in argv and "/home/u" in argv
    assert "{worktree}" not in argv and "{home}" not in argv


def test_empty_cmd_is_skipped(tmp_path):
    c = _config(tmp_path)
    s = gate.run_step("lint", "", str(tmp_path), c)
    assert s.skipped and s.passed


@needs_bwrap
def test_passing_check_claude_author_passes(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "add.py").write_text("def add(a, b):\n    return a + b\n")
    (wt / "test_add.py").write_text(
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    t = _task(tmp_path, author="claude")
    r = gate.run_gate(t, str(wt), _config(tmp_path))
    assert r.status == "passed"
    assert any(s.name == "check" and s.passed for s in r.steps)


@needs_bwrap
def test_passing_check_worker_author_is_needs_human(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "add.py").write_text("def add(a, b):\n    return a + b\n")
    (wt / "test_add.py").write_text(
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    t = _task(tmp_path, author="worker")            # worker-authored check → never auto-passed
    r = gate.run_gate(t, str(wt), _config(tmp_path))
    assert r.status == "needs_human"


@needs_bwrap
def test_failing_check_is_failed(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "add.py").write_text("def add(a, b):\n    return a - b\n")   # wrong
    (wt / "test_add.py").write_text(
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    t = _task(tmp_path, author="claude")
    r = gate.run_gate(t, str(wt), _config(tmp_path))
    assert r.status == "failed"


@needs_bwrap
def test_worker_author_failing_check_is_needs_human(tmp_path):
    # A worker-authored check is untrustworthy whether it passes OR fails; with the
    # trusted repo steps clean, a failing worker check still routes to needs_human.
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "add.py").write_text("def add(a, b):\n    return a - b\n")   # wrong
    (wt / "test_add.py").write_text(
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    t = _task(tmp_path, author="worker")
    r = gate.run_gate(t, str(wt), _config(tmp_path))
    assert r.status == "needs_human"
