import subprocess
from types import SimpleNamespace

from orchestration.loop import gate


def test_timeout_returns_failed_step(monkeypatch):
    fake_run = lambda *a, **kw: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(cmd="x", timeout=5)
    )
    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    config = SimpleNamespace(
        gate=SimpleNamespace(sandbox="true", timeout=5),
        home="/tmp",
    )
    r = gate.run_step("check", "pytest -q", "/tmp", config)

    assert r.passed is False
    assert r.timed_out is True
    assert r.exit_code == -1
    assert "TIMEOUT" in r.stderr
    assert r.skipped is False


def test_missing_sandbox_binary_returns_failed_step(monkeypatch):
    fake_run = lambda *a, **kw: (_ for _ in ()).throw(
        FileNotFoundError("no such binary")
    )
    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    config = SimpleNamespace(
        gate=SimpleNamespace(sandbox="true", timeout=5),
        home="/tmp",
    )
    r = gate.run_step("check", "pytest -q", "/tmp", config)

    assert r.passed is False
    assert r.exit_code == -1
    assert "failed to launch" in r.stderr
    assert r.timed_out is False
