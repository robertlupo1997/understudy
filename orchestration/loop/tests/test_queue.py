import textwrap
import pytest
from orchestration.loop import queue as q


def _write_task(tmp_path, name="t1", status="queued", author="claude",
                complexity="simple", target='[add.py]'):
    p = tmp_path / f"{name}.md"
    p.write_text(textwrap.dedent(f"""\
        ---
        id: {name}
        title: "T {name}"
        complexity: {complexity}
        check_author: {author}
        check_cmd: "python3 -m pytest test_add.py -q"
        target_files: {target}
        status: {status}
        context: |
          line one
          line two
        ---
        Prose body describing the task.
        """))
    return p


def test_parse_task_reads_all_fields(tmp_path):
    t = q.parse_task(str(_write_task(tmp_path)))
    assert t.id == "t1"
    assert t.complexity == "simple"
    assert t.check_author == "claude"
    assert t.target_files == ["add.py"]
    assert t.status == "queued"
    assert "line one" in t.context and "line two" in t.context
    assert "Prose body" in t.prose


def test_parse_rejects_bad_enum(tmp_path):
    with pytest.raises(q.QueueError):
        q.parse_task(str(_write_task(tmp_path, complexity="epic")))


def test_list_queued_only_queued_sorted(tmp_path):
    _write_task(tmp_path, name="b", status="queued")
    _write_task(tmp_path, name="a", status="queued")
    _write_task(tmp_path, name="c", status="done")
    ids = [t.id for t in q.list_queued(str(tmp_path))]
    assert ids == ["a", "b"]


def test_set_status_rewrites_frontmatter_only(tmp_path):
    p = _write_task(tmp_path, name="t1", status="queued")
    t = q.parse_task(str(p))
    q.set_status(t, "running")
    assert t.status == "running"
    reparsed = q.parse_task(str(p))
    assert reparsed.status == "running"
    # prose + context preserved verbatim
    assert "Prose body describing the task." in p.read_text()
    assert "line two" in reparsed.context


def test_list_queued_skips_malformed_files(tmp_path, capsys):
    _write_task(tmp_path, name="good")
    (tmp_path / "broken.md").write_text("no frontmatter here")
    tasks = q.list_queued(str(tmp_path))
    assert [t.id for t in tasks] == ["good"]            # daemon survives a poison queue file
    assert "broken.md" in capsys.readouterr().out       # skip is logged, not silent
