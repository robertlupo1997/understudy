"""The 24/7 driver (spec §8). Zero Claude tokens while grinding. Per task:
worktree add off base -> worker -> commit on branch -> capture diff -> sandboxed
gate -> inbox record -> mark task status -> remove worktree (branch persists).
Nothing merges automatically (propose-only)."""
import argparse
import os
import shutil
import subprocess
import time
import traceback
import urllib.request

from orchestration.loop import config as _config
from orchestration.loop import queue
from orchestration.loop import gate
from orchestration.loop import inbox
from orchestration.loop import maintenance
from orchestration.loop import worker_adapter

STATUS_MAP = {"passed": "done", "failed": "failed", "needs_human": "needs_human"}
_DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "config.yaml")


def resolve_config_path(argv):
    ap = argparse.ArgumentParser(prog="run_loop")
    ap.add_argument("--config", default=_DEFAULT_CONFIG,
                    help="path to the loop config YAML (default: bundled config.yaml)")
    return ap.parse_args(argv).config


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout


def _record_error(config, task, exc):
    """Best-effort error record — swallows any Exception so a record failure
    never masks the original error (system-exiting BaseExceptions propagate)."""
    try:
        inbox.write_error_record(config, task, repr(exc), traceback.format_exc())
    except Exception as e:
        print(f"[run_loop] could not write error record for {task.id}: {e}")


def process_task(task, config, worker_fn):
    base_sha = _git(config.target_repo, "rev-parse", "HEAD").strip()
    branch = f"{config.branch_prefix}/{task.id}"
    wt = os.path.join(config.worktrees_dir, task.id)
    os.makedirs(config.worktrees_dir, exist_ok=True)
    t0 = time.time()

    queue.set_status(task, "running")
    try:
        _git(config.target_repo, "worktree", "add", "-b", branch, wt, base_sha)
    except subprocess.CalledProcessError as e:
        queue.set_status(task, "failed")   # worktree add failed → never leave the task "running"
        _record_error(config, task, e)
        shutil.rmtree(wt, ignore_errors=True)   # sweep any partial worktree dir (finally below never runs)
        raise
    recorded = False
    try:
        wr = worker_fn(task, wt, config)
        # Commit whatever the worker wrote (allow-empty so the branch/diff exists
        # even on worker failure — the diff is captured from committed state so a
        # read-only gate cannot pollute the proposal).
        _git(wt, "add", "-A")
        # Fixed bot identity so the automated commit never depends on ambient
        # ~/.gitconfig (robust under a stripped-env daemon / a sandboxed re-run).
        _git(wt, "-c", f"user.name={config.bot_name}", "-c", f"user.email={config.bot_email}",
             "commit", "--allow-empty", "-m", f"{config.commit_prefix}: {task.id}")
        diff = _git(config.target_repo, "diff", f"{base_sha}..{branch}")

        if wr.ok:
            gr = gate.run_gate(task, wt, config)
        else:
            gr = gate.GateResult("failed", [])

        durations = {"total_s": round(time.time() - t0, 1)}
        inbox.write_record(config, task, wr, gr, diff, base_sha, branch, durations)
        recorded = True
        final = gr.status if wr.ok else "failed"
        queue.set_status(task, STATUS_MAP.get(final, "failed"))
        return final
    except Exception as e:
        queue.set_status(task, "failed")   # any unexpected failure → mark failed, never "running"
        if not recorded:                   # a full record already landed; never overwrite it
            _record_error(config, task, e)
        raise
    finally:
        _git(config.target_repo, "worktree", "remove", "--force", wt)


def run_once(config, worker_fn=None):
    if worker_fn is None:
        worker_fn = worker_adapter.run_worker
    tasks = queue.list_queued(config.queue_dir)
    for task in tasks:                          # v1: serial (max_parallel=1, single GPU)
        try:
            process_task(task, config, worker_fn)
        except Exception as e:                  # poison-task isolation: one bad task must not halt the pass
            print(f"[run_loop] task {task.id} errored, marked failed: {e}")
    return len(tasks)


def health_check(config):
    try:
        with urllib.request.urlopen(
                config.endpoint.rstrip("/") + "/models", timeout=5) as r:
            return getattr(r, "status", 200) == 200
    except OSError:
        return False


def _tick(config, worker_fn=None):
    """One scheduler beat. Returns seconds to sleep before the next beat
    (0 = more work may be immediately available)."""
    if not health_check(config):
        print("[run_loop] endpoint unreachable; sleeping 30s")
        return 30
    if run_once(config, worker_fn):
        return 0
    if maintenance.promote_next(config):
        return 0                                # promoted; process it next beat
    return 30                                   # queue and backlog both dry


def main(argv=None):
    import sys
    config = _config.load_config(resolve_config_path(sys.argv[1:] if argv is None else argv))
    if config.max_parallel != 1:
        print(f"[run_loop] warning: max_parallel={config.max_parallel} "
              f"not supported in v1; running serially")
    while True:
        s = _tick(config)
        if s:
            time.sleep(s)


if __name__ == "__main__":
    main()
