import os
import shutil
import subprocess
import textwrap
import pytest
from orchestration.loop import run_loop
from orchestration.loop import config as cfg
from orchestration.loop.worker_adapter import WorkerResult
from orchestration.loop.tests.conftest import write_config_yaml

pytestmark = pytest.mark.sandbox            # spawns bwrap + needs ambient git; excluded from the no-regression leg
needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap required")


def _seed_task(queue_dir, tid="t1", author="claude"):
    os.makedirs(queue_dir, exist_ok=True)
    p = os.path.join(queue_dir, f"{tid}.md")
    with open(p, "w") as f:
        f.write(textwrap.dedent(f"""\
            ---
            id: {tid}
            title: "Add"
            complexity: simple
            check_author: {author}
            check_cmd: "python3 -m pytest test_add.py -q"
            target_files: [add.py]
            status: queued
            context: ""
            ---
            Implement add(a, b) returning a + b.
            """))
    return p


@needs_bwrap
def test_process_task_lands_gated_diff_and_never_touches_base(temp_repo, tmp_path):
    # Claude-authored check lives in the base commit (so it's in the worktree)
    (temp_repo / "test_add.py").write_text(
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run(["git", "-C", str(temp_repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(temp_repo), "commit", "-qm", "add check"], check=True)
    base = subprocess.run(["git", "-C", str(temp_repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    _seed_task(c.queue_dir)

    def fake_worker(task, worktree, config):
        with open(os.path.join(worktree, "add.py"), "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        return WorkerResult(True, 0, "files changed: add.py\nwhat was done: wrote 2 lines",
                            "", "fake")

    n = run_loop.run_once(c, worker_fn=fake_worker)
    assert n == 1

    # inbox record with a gated, passing diff
    meta_path = os.path.join(c.inbox_dir, "t1", "meta.json")
    assert os.path.isfile(meta_path)
    import json
    meta = json.load(open(meta_path))
    assert meta["status"] == "passed"
    assert "+def add" in open(os.path.join(c.inbox_dir, "t1", "diff.patch")).read()

    # propose-only: base commit unchanged, branch exists, worktree cleaned up
    head_now = subprocess.run(["git", "-C", str(temp_repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    assert head_now == base
    branches = subprocess.run(["git", "-C", str(temp_repo), "branch"],
                              capture_output=True, text=True).stdout
    assert "ornith/t1" in branches
    assert not os.path.exists(os.path.join(c.worktrees_dir, "t1"))

    # queue task marked done
    from orchestration.loop import queue as q
    assert q.parse_task(os.path.join(c.queue_dir, "t1.md")).status == "done"


@needs_bwrap
def test_run_once_isolates_and_recovers_from_a_raising_worker(temp_repo, tmp_path):
    # Claude-authored check lives in base (so it's in the worktree for the good task)
    (temp_repo / "test_add.py").write_text(
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run(["git", "-C", str(temp_repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(temp_repo), "commit", "-qm", "add check"], check=True)

    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    _seed_task(c.queue_dir, tid="bad")
    _seed_task(c.queue_dir, tid="good")

    calls = []

    def worker_fn(task, worktree, config):
        calls.append(task.id)
        if task.id == "bad":
            raise RuntimeError("boom")
        with open(os.path.join(worktree, "add.py"), "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        return WorkerResult(True, 0, "files changed: add.py", "", "fake")

    n = run_loop.run_once(c, worker_fn=worker_fn)        # must NOT raise despite the poison task
    assert n == 2
    assert calls == ["bad", "good"]             # the bad task did not halt the loop

    from orchestration.loop import queue as q
    assert q.parse_task(os.path.join(c.queue_dir, "bad.md")).status == "failed"   # not stuck "running"
    assert q.parse_task(os.path.join(c.queue_dir, "good.md")).status == "done"
    assert not os.path.exists(os.path.join(c.worktrees_dir, "bad"))               # worktree cleaned up
    assert not os.path.exists(os.path.join(c.worktrees_dir, "good"))


def test_hard_worker_exception_writes_error_record(temp_repo, tmp_path):
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    _seed_task(c.queue_dir, tid="bad")

    def worker_fn(task, worktree, config):
        raise RuntimeError("boom")

    n = run_loop.run_once(c, worker_fn=worker_fn)       # poison isolation: must not raise
    assert n == 1
    import json
    meta = json.load(open(os.path.join(c.inbox_dir, "bad", "meta.json")))
    assert meta["status"] == "failed"
    assert "boom" in meta["error"]
    tb = open(os.path.join(c.inbox_dir, "bad", "logs", "error.txt")).read()
    assert "RuntimeError" in tb
    from orchestration.loop import queue as q
    assert q.parse_task(os.path.join(c.queue_dir, "bad.md")).status == "failed"


def test_worktree_add_failure_writes_error_record_and_sweeps(temp_repo, tmp_path):
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    _seed_task(c.queue_dir, tid="t1")
    # Pre-create the branch so `git worktree add -b ornith/t1` fails.
    subprocess.run(["git", "-C", str(temp_repo), "branch", "ornith/t1"], check=True)

    def worker_fn(task, worktree, config):
        raise AssertionError("worker must not run when worktree add fails")

    n = run_loop.run_once(c, worker_fn=worker_fn)
    assert n == 1
    import json
    meta = json.load(open(os.path.join(c.inbox_dir, "t1", "meta.json")))
    assert meta["status"] == "failed"
    assert not os.path.exists(os.path.join(c.worktrees_dir, "t1"))  # partial dir swept
    from orchestration.loop import queue as q
    assert q.parse_task(os.path.join(c.queue_dir, "t1.md")).status == "failed"


def test_error_record_failure_does_not_mask_original(temp_repo, tmp_path):
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    _seed_task(c.queue_dir, tid="bad")
    (temp_repo / "inbox").write_text("not a dir")       # write_error_record's makedirs will fail

    def worker_fn(task, worktree, config):
        raise RuntimeError("original boom")

    from orchestration.loop import queue as q
    task = q.parse_task(os.path.join(c.queue_dir, "bad.md"))
    with pytest.raises(RuntimeError, match="original boom"):
        run_loop.process_task(task, c, worker_fn)
    assert q.parse_task(os.path.join(c.queue_dir, "bad.md")).status == "failed"


def test_tick_promotes_when_idle_and_sleeps_when_dry(temp_repo, tmp_path, monkeypatch):
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    monkeypatch.setattr(run_loop, "health_check", lambda config: True)
    _seed_task(c.backlog_dir, tid="b1")

    assert run_loop._tick(c) == 0                       # idle queue → promoted → no sleep
    assert os.path.exists(os.path.join(c.queue_dir, "b1.md"))

    os.remove(os.path.join(c.queue_dir, "b1.md"))
    assert run_loop._tick(c) == 30                      # queue and backlog both dry → sleep


def test_tick_sleeps_when_endpoint_down(temp_repo, tmp_path, monkeypatch):
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    monkeypatch.setattr(run_loop, "health_check", lambda config: False)
    assert run_loop._tick(c) == 30


@needs_bwrap
def test_idle_loop_promotes_then_processes_backlog_task(temp_repo, tmp_path, monkeypatch):
    # Claude-authored check lives in base (so it's in the worktree)
    (temp_repo / "test_add.py").write_text(
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run(["git", "-C", str(temp_repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(temp_repo), "commit", "-qm", "add check"], check=True)

    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    monkeypatch.setattr(run_loop, "health_check", lambda config: True)
    _seed_task(c.backlog_dir, tid="b1")

    def fake_worker(task, worktree, config):
        with open(os.path.join(worktree, "add.py"), "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        return WorkerResult(True, 0, "files changed: add.py", "", "fake")

    assert run_loop._tick(c, worker_fn=fake_worker) == 0    # beat 1: promotes b1
    assert run_loop._tick(c, worker_fn=fake_worker) == 0    # beat 2: processes b1
    import json
    meta = json.load(open(os.path.join(c.inbox_dir, "b1", "meta.json")))
    assert meta["status"] == "passed"
    assert run_loop._tick(c, worker_fn=fake_worker) == 30   # beat 3: dry → sleep


def test_terminal_set_status_failure_does_not_overwrite_full_record(temp_repo, tmp_path, monkeypatch):
    # M1 guard: if the terminal set_status raises AFTER write_record landed a full
    # record, the error-record fallback must not overwrite it.
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    _seed_task(c.queue_dir, tid="t1")

    from orchestration.loop import queue as q
    real_set_status = q.set_status
    failed_once = []

    def flaky_set_status(task, status):
        if status != "running" and not failed_once:
            failed_once.append(status)
            raise q.QueueError("simulated set_status failure")
        return real_set_status(task, status)

    monkeypatch.setattr(run_loop.queue, "set_status", flaky_set_status)

    def worker_fn(task, worktree, config):
        return WorkerResult(False, 1, "", "worker failed", "fake")

    n = run_loop.run_once(c, worker_fn=worker_fn)       # poison isolation: must not raise
    assert n == 1
    import json
    meta = json.load(open(os.path.join(c.inbox_dir, "t1", "meta.json")))
    assert meta["model"] == "fake"                      # full record survived
    assert "error" not in meta                          # not overwritten by minimal error record
    assert q.parse_task(os.path.join(c.queue_dir, "t1.md")).status == "failed"  # recovery still ran
