import os
import textwrap
from orchestration.loop import config as cfg
from orchestration.loop import maintenance
from orchestration.loop.tests.conftest import write_config_yaml


def _cfg(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", repo)))
    os.makedirs(c.backlog_dir, exist_ok=True)
    os.makedirs(c.queue_dir, exist_ok=True)
    return c


def _item(dirpath, tid, status="queued"):
    p = os.path.join(str(dirpath), f"{tid}.md")
    with open(p, "w") as f:
        f.write(textwrap.dedent(f"""\
            ---
            id: {tid}
            title: "T {tid}"
            complexity: simple
            check_author: worker
            check_cmd: "python3 -m pytest -q"
            target_files: [x.py]
            status: {status}
            context: ""
            ---
            body
            """))
    return p


def test_promotes_oldest_when_queue_empty(tmp_path):
    c = _cfg(tmp_path)
    _item(c.backlog_dir, "b2")
    _item(c.backlog_dir, "b1")
    assert maintenance.promote_next(c) == "b1"          # sorted filename order
    assert os.path.exists(os.path.join(c.queue_dir, "b1.md"))
    assert not os.path.exists(os.path.join(c.backlog_dir, "b1.md"))
    assert os.path.exists(os.path.join(c.backlog_dir, "b2.md"))    # one at a time


def test_no_promotion_when_queue_has_work(tmp_path):
    c = _cfg(tmp_path)
    _item(c.queue_dir, "q1")
    _item(c.backlog_dir, "b1")
    assert maintenance.promote_next(c) is None
    assert os.path.exists(os.path.join(c.backlog_dir, "b1.md"))


def test_none_when_backlog_missing_or_unconfigured(tmp_path):
    c = _cfg(tmp_path)
    assert maintenance.promote_next(c) is None          # backlog dir empty
    c.backlog_dir = None
    assert maintenance.promote_next(c) is None          # feature off


def test_skips_malformed_and_non_queued_items(tmp_path, capsys):
    c = _cfg(tmp_path)
    with open(os.path.join(c.backlog_dir, "a-bad.md"), "w") as f:
        f.write("no frontmatter")
    _item(c.backlog_dir, "b-done", status="done")
    _item(c.backlog_dir, "c-good")
    assert maintenance.promote_next(c) == "c-good"
    assert "a-bad" in capsys.readouterr().out           # skip is logged
    assert os.path.exists(os.path.join(c.backlog_dir, "a-bad.md"))   # left in place, never deleted


def test_never_clobbers_existing_queue_file(tmp_path):
    c = _cfg(tmp_path)
    _item(c.backlog_dir, "dup")
    _item(c.queue_dir, "dup", status="done")            # same filename in queue, not queued → queue is idle
    assert maintenance.promote_next(c) is None
    assert os.path.exists(os.path.join(c.backlog_dir, "dup.md"))     # untouched
