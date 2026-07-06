import json
import os
import subprocess
import textwrap
import pytest
from orchestration.loop import inbox
from orchestration.loop import queue as q
from orchestration.loop import config as cfg
from orchestration.loop.gate import GateResult, StepResult
from orchestration.loop.worker_adapter import WorkerResult
from orchestration.loop.tests.conftest import write_config_yaml


def _task(tmp_path, author="claude"):
    p = tmp_path / "t.md"
    p.write_text(textwrap.dedent(f"""\
        ---
        id: t1
        title: "Add"
        complexity: simple
        check_author: {author}
        check_cmd: "true"
        target_files: [add.py]
        status: running
        context: ""
        ---
        body
        """))
    return q.parse_task(str(p))


def _config(tmp_path, repo):
    return cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", repo)))


def test_write_record_layout_and_no_log_leak(tmp_path):
    c = _config(tmp_path, tmp_path)
    t = _task(tmp_path)
    wr = WorkerResult(True, 0, "files changed: /x\nwhat was done: wrote 2 lines", "wstderr", "ornith9b")
    gr = GateResult("passed", [
        StepResult("check", "true", 0, True, "SECRET_MODEL_STDOUT", "gate_err"),
        StepResult("lint", "", 0, True, "", "", skipped=True),
    ])
    rec = inbox.write_record(c, t, wr, gr, "diff --git a/x", "abc123", "ornith/t1", {"total_s": 1.2})
    assert os.path.isdir(rec)
    meta = json.load(open(os.path.join(rec, "meta.json")))
    assert meta["status"] == "passed" and meta["branch"] == "ornith/t1"
    summary = open(os.path.join(rec, "summary.md")).read()
    assert "files changed" in summary                       # bounded worker summary present
    assert "check: PASS" in summary
    assert "SECRET_MODEL_STDOUT" not in summary             # gate stdout NEVER in summary (token contract)
    assert "SECRET_MODEL_STDOUT" in open(os.path.join(rec, "logs", "check.stdout")).read()
    assert open(os.path.join(rec, "diff.patch")).read() == "diff --git a/x"


def test_list_records(tmp_path):
    c = _config(tmp_path, tmp_path)
    t = _task(tmp_path)
    wr = WorkerResult(True, 0, "s", "", "ornith9b")
    inbox.write_record(c, t, wr, GateResult("failed", []), "d", "sha", "ornith/t1", {})
    recs = inbox.list_records(c.inbox_dir)
    assert len(recs) == 1 and recs[0]["id"] == "t1" and recs[0]["status"] == "failed"


def test_approve_refuses_main(temp_repo, tmp_path):
    # put repo on main, expect refusal
    subprocess.run(["git", "-C", str(temp_repo), "checkout", "-q", "-B", "main"], check=True)
    c = _config(tmp_path, temp_repo)
    with pytest.raises(inbox.InboxError):
        inbox.approve(c, "whatever")


def test_reject_deletes_branch_and_archives(temp_repo, tmp_path):
    c = _config(tmp_path, temp_repo)
    # make a branch to reject
    subprocess.run(["git", "-C", str(temp_repo), "branch", "ornith/t1"], check=True)
    t = _task(tmp_path)
    inbox.write_record(c, t, WorkerResult(True, 0, "s", "", "m"), GateResult("failed", []),
                       "d", "sha", "ornith/t1", {})
    inbox.reject(c, "t1")
    branches = subprocess.run(["git", "-C", str(temp_repo), "branch"],
                              capture_output=True, text=True).stdout
    assert "ornith/t1" not in branches
    assert os.path.isdir(os.path.join(c.inbox_dir, "_rejected", "t1"))


def test_write_error_record_minimal_layout(tmp_path):
    c = _config(tmp_path, tmp_path)
    t = _task(tmp_path)
    rec = inbox.write_error_record(c, t, "RuntimeError('boom')", "Traceback (most recent call last):\n  ...")
    meta = json.load(open(os.path.join(rec, "meta.json")))
    assert meta["id"] == "t1"
    assert meta["title"] == "Add"
    assert meta["check_author"] == "claude"
    assert meta["status"] == "failed"
    assert "boom" in meta["error"]
    assert meta["gate_steps"] == []                     # gate never ran
    s = open(os.path.join(rec, "summary.md")).read()
    assert "hard error" in s and "boom" in s
    assert "Traceback" not in s                         # token contract: tb -> logs only
    assert "Traceback" in open(os.path.join(rec, "logs", "error.txt")).read()


def test_write_error_record_bounds_summary(tmp_path):
    c = _config(tmp_path, tmp_path)
    t = _task(tmp_path)
    big = "x" * 100_000
    rec = inbox.write_error_record(c, t, big, big)
    assert len(open(os.path.join(rec, "summary.md")).read()) < 1000
    meta = json.load(open(os.path.join(rec, "meta.json")))
    assert len(meta["error"]) <= 500


def test_write_error_record_listable(tmp_path):
    c = _config(tmp_path, tmp_path)
    t = _task(tmp_path)
    inbox.write_error_record(c, t, "boom", "")
    recs = inbox.list_records(c.inbox_dir)
    assert [r["id"] for r in recs] == ["t1"]
    assert recs[0]["status"] == "failed"
