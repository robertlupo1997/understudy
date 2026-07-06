"""Route a queue Task to the hardened one-shot worker (orchestration/ornith_worker.py).

v1 handles single-file tasks only; multi-file work is decomposed by Claude at
planning time (spec §7). Returns a bounded WorkerResult — raw model output stays
on disk/logs, never here (token contract, spec §9)."""
import os
import subprocess
import sys
from dataclasses import dataclass

_WORKER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "ornith_worker.py"))


class WorkerAdapterError(Exception):
    """Task cannot be routed to the one-shot worker."""


@dataclass
class WorkerResult:
    ok: bool
    exit_code: int
    summary: str
    stderr: str
    model: str


def build_prompt(task):
    parts = [task.title.strip(), task.prose.strip()]
    ctx = task.context.strip()
    if ctx:
        parts.append("Context:\n" + ctx)
    return "\n\n".join(p for p in parts if p)


def run_worker(task, worktree, config):
    if len(task.target_files) != 1:
        raise WorkerAdapterError(
            f"v1 one-shot worker requires exactly one target_files entry, "
            f"got {task.target_files}")
    model = config.models["simple" if task.complexity == "simple" else "complex"]
    out = os.path.join(worktree, task.target_files[0])
    cmd = [
        sys.executable, _WORKER,
        "--task", build_prompt(task),
        "--out", out,
        "--allowed-dir", worktree,
        "--model", model,
        "--base", config.endpoint,
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=config.gate.timeout + 60)
    except subprocess.TimeoutExpired as e:
        return WorkerResult(False, -1, "", f"worker timed out: {e}", model)
    return WorkerResult(p.returncode == 0, p.returncode, p.stdout, p.stderr, model)
