"""Run task-check + repo no-regression inside a bwrap sandbox (spec §6).

Only model-authored code runs here, so it runs ONLY in a child process under an
OS sandbox: no network (--unshare-all), read-only host with $HOME secrets blanked,
worktree read-only, /tmp tmpfs scratch, wall-clock timeout (SIGKILL + --die-with-parent).
An auto-'passed' badge is earned ONLY when check_author == 'claude' (spec §5)."""
import shlex
import subprocess
from dataclasses import dataclass, field


@dataclass
class StepResult:
    name: str
    cmd: str
    exit_code: int
    passed: bool
    stdout: str
    stderr: str
    timed_out: bool = False
    skipped: bool = False


@dataclass
class GateResult:
    status: str
    steps: list = field(default_factory=list)


def build_sandbox_argv(sandbox_template, worktree, home):
    filled = sandbox_template.replace("{worktree}", worktree).replace("{home}", home)
    return shlex.split(filled)


def run_step(name, cmd, worktree, config):
    if not cmd.strip():
        return StepResult(name, cmd, 0, True, "", "", skipped=True)
    argv = (build_sandbox_argv(config.gate.sandbox, worktree, config.home)
            + ["--"] + shlex.split(cmd))
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=config.gate.timeout)
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else ""
        err = e.stderr if isinstance(e.stderr, str) else ""
        return StepResult(name, cmd, -1, False, out,
                          f"{err}\nTIMEOUT after {config.gate.timeout}s", timed_out=True)
    except FileNotFoundError as e:                 # sandbox binary missing, etc.
        return StepResult(name, cmd, -1, False, "", f"failed to launch: {e}")
    return StepResult(name, cmd, p.returncode, p.returncode == 0, p.stdout, p.stderr)


def run_gate(task, worktree, config):
    steps = [
        run_step("setup", config.gate.setup_cmd, worktree, config),
        run_step("check", task.check_cmd, worktree, config),
        run_step("test", config.gate.test_cmd, worktree, config),
        run_step("lint", config.gate.lint_cmd, worktree, config),
        run_step("typecheck", config.gate.typecheck_cmd, worktree, config),
    ]
    # Trusted (author-independent) steps — setup/test/lint/typecheck — are a real
    # regression signal regardless of who wrote the task check. The "check" step is
    # only trustworthy when Claude authored it.
    trusted_ok = all(s.passed for s in steps if s.name != "check")
    check_step = next(s for s in steps if s.name == "check")
    if not trusted_ok:
        status = "failed"                          # model broke the repo (trusted no-regression/lint/typecheck)
    elif task.check_author != "claude":
        status = "needs_human"                     # worker-authored check is never an automated verdict (pass OR fail)
    elif check_step.passed:
        status = "passed"
    else:
        status = "failed"                          # Claude-authored check failed
    return GateResult(status, steps)
