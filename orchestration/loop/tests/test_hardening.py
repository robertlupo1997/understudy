import pytest
from orchestration.loop import queue as q


def test_queue_rejects_no_frontmatter(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("just prose, no frontmatter\n")
    with pytest.raises(q.QueueError):
        q.parse_task(str(p))


def test_queue_rejects_non_mapping_frontmatter(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("---\n- a\n- b\n---\nbody\n")
    with pytest.raises(q.QueueError):
        q.parse_task(str(p))


def test_queue_rejects_empty_target_files(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("---\nid: x\ntitle: t\ncomplexity: simple\ncheck_author: claude\n"
                 "check_cmd: 'true'\ntarget_files: []\nstatus: queued\n---\nbody\n")
    with pytest.raises(q.QueueError):
        q.parse_task(str(p))
