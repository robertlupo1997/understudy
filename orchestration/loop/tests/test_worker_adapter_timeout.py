import subprocess
from types import SimpleNamespace

import pytest

from orchestration.loop import worker_adapter


def test_timeout_returns_failed_result(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(worker_adapter.subprocess, "run", fake_run)

    task = SimpleNamespace(
        target_files=["a.py"],
        complexity="simple",
        title="t",
        prose="",
        context="",
    )
    config = SimpleNamespace(
        models={"simple": "m9", "complex": "m35"},
        endpoint="http://localhost:1",
        gate=SimpleNamespace(timeout=1),
    )

    result = worker_adapter.run_worker(task, "/tmp", config)

    assert result.ok is False
    assert result.exit_code == -1
    assert "timed out" in result.stderr
    assert result.model == "m9"


def test_complex_task_selects_complex_model_on_timeout(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(worker_adapter.subprocess, "run", fake_run)

    task = SimpleNamespace(
        target_files=["a.py"],
        complexity="complex",
        title="t",
        prose="",
        context="",
    )
    config = SimpleNamespace(
        models={"simple": "m9", "complex": "m35"},
        endpoint="http://localhost:1",
        gate=SimpleNamespace(timeout=1),
    )

    result = worker_adapter.run_worker(task, "/tmp", config)

    assert result.ok is False
    assert result.exit_code == -1
    assert "timed out" in result.stderr
    assert result.model == "m35"
