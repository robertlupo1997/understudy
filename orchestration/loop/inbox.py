"""Write/read the propose-only inbox record (spec §5). approve = merge branch;
reject = delete branch + archive. summary.md carries ONLY the worker's bounded
summary + gate PASS/FAIL tags; all raw stdout/stderr goes to logs/ (token contract)."""
import json
import os
import subprocess


class InboxError(Exception):
    """Inbox operation failed."""


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


def _tag(step):
    if step.skipped:
        return "skip"
    if step.timed_out:
        return "TIMEOUT"
    return "PASS" if step.passed else "FAIL"


def write_record(config, task, worker_result, gate_result, diff_text,
                 base_sha, branch, durations):
    rec = os.path.join(config.inbox_dir, task.id)
    logs = os.path.join(rec, "logs")
    os.makedirs(logs, exist_ok=True)

    meta = {
        "id": task.id,
        "title": task.title,
        "status": gate_result.status,
        "model": worker_result.model,
        "worker_ok": worker_result.ok,
        "worker_exit": worker_result.exit_code,
        "check_author": task.check_author,
        "base_sha": base_sha,
        "branch": branch,
        "gate_steps": [
            {"name": s.name, "passed": s.passed, "exit": s.exit_code,
             "skipped": s.skipped, "timed_out": s.timed_out}
            for s in gate_result.steps
        ],
        "durations": durations,
    }
    _write(os.path.join(rec, "meta.json"), json.dumps(meta, indent=2))
    _write(os.path.join(rec, "diff.patch"), diff_text)

    lines = [f"# {task.id} — {gate_result.status}", "",
             "## Worker", worker_result.summary or "(no summary)", "", "## Gate"]
    for s in gate_result.steps:
        lines.append(f"- {s.name}: {_tag(s)} (exit {s.exit_code})")
    _write(os.path.join(rec, "summary.md"), "\n".join(lines) + "\n")

    _write(os.path.join(logs, "worker.stderr"), worker_result.stderr or "")
    for s in gate_result.steps:
        if not s.skipped:
            _write(os.path.join(logs, f"{s.name}.stdout"), s.stdout or "")
            _write(os.path.join(logs, f"{s.name}.stderr"), s.stderr or "")
    return rec


def write_error_record(config, task, error, traceback_text=""):
    """Minimal record for a task that died before the gate could run (hard
    worker exception / worktree-add failure) — the inbox stays the single
    pane of glass. Token contract: summary.md gets ONE bounded error line;
    the full traceback goes to logs/error.txt only. Exception-path callers
    must wrap this best-effort (see run_loop._record_error)."""
    rec = os.path.join(config.inbox_dir, task.id)
    logs = os.path.join(rec, "logs")
    os.makedirs(logs, exist_ok=True)
    err = " ".join(str(error).split())[:500] or "(no message)"
    meta = {
        "id": task.id,
        "title": task.title,
        "status": "failed",
        "error": err,
        "check_author": task.check_author,
        "gate_steps": [],
    }
    _write(os.path.join(rec, "meta.json"), json.dumps(meta, indent=2))
    _write(os.path.join(rec, "summary.md"),
           f"# {task.id} — failed (hard error, gate never ran)\n\n{err}\n")
    _write(os.path.join(logs, "error.txt"), traceback_text or str(error))
    return rec


def list_records(inbox_dir):
    out = []
    if not os.path.isdir(inbox_dir):
        return out
    for name in sorted(os.listdir(inbox_dir)):
        mp = os.path.join(inbox_dir, name, "meta.json")
        if os.path.isfile(mp):
            with open(mp) as f:
                out.append(json.load(f))
    return out


def show(inbox_dir, task_id):
    with open(os.path.join(inbox_dir, task_id, "summary.md")) as f:
        return f.read()


def approve(config, task_id):
    cur = _git(config.target_repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if cur in ("main", "master"):
        raise InboxError(f"refusing to merge onto {cur} (propose-only, spec §10)")
    _git(config.target_repo, "merge", "--no-ff", "-m",
         f"approve ornith/{task_id}", f"ornith/{task_id}")


def reject(config, task_id):
    _git(config.target_repo, "branch", "-D", f"ornith/{task_id}")
    rec = os.path.join(config.inbox_dir, task_id)
    if os.path.isdir(rec):
        arch = os.path.join(config.inbox_dir, "_rejected")
        os.makedirs(arch, exist_ok=True)
        os.replace(rec, os.path.join(arch, task_id))
