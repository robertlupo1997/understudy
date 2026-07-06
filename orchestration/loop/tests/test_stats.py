"""Claude-authored check for stats.count_by_status (dogfood task, 2026-07-01).

check_author: claude — written before, and independently of, the worker's
implementation. TDD: RED on main until the ornith/<id> proposal is merged.
"""
from orchestration.loop import stats


def _task(tmp_path, name, status):
    (tmp_path / name).write_text(
        f"---\nid: {name}\ntitle: t\nstatus: {status}\n---\nprose\n")


def test_counts_by_status(tmp_path):
    _task(tmp_path, "a.md", "queued")
    _task(tmp_path, "b.md", "queued")
    _task(tmp_path, "c.md", "done")
    assert stats.count_by_status(str(tmp_path)) == {"queued": 2, "done": 1}


def test_empty_dir_gives_empty_dict(tmp_path):
    assert stats.count_by_status(str(tmp_path)) == {}


def test_file_without_status_line_is_ignored(tmp_path):
    (tmp_path / "noise.md").write_text("no frontmatter here\n")
    _task(tmp_path, "a.md", "failed")
    assert stats.count_by_status(str(tmp_path)) == {"failed": 1}


def test_first_status_line_wins(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\nid: a\nstatus: queued\n---\nbody mentions\nstatus: done\n")
    assert stats.count_by_status(str(tmp_path)) == {"queued": 1}


def test_non_md_files_are_ignored(tmp_path):
    (tmp_path / "a.txt").write_text("status: queued\n")
    _task(tmp_path, "b.md", "running")
    assert stats.count_by_status(str(tmp_path)) == {"running": 1}
