"""Load and validate the loop config (spec §15). PyYAML safe_load only."""
import os
from dataclasses import dataclass

import yaml


class ConfigError(Exception):
    """Malformed or incomplete config."""


@dataclass
class GateConfig:
    setup_cmd: str
    test_cmd: str
    lint_cmd: str
    typecheck_cmd: str
    sandbox: str
    timeout: int


@dataclass
class Config:
    target_repo: str
    queue_dir: str
    inbox_dir: str
    worktrees_dir: str
    endpoint: str
    models: dict
    fallback: dict
    gate: GateConfig
    max_parallel: int
    home: str
    backlog_dir: str | None = None    # optional; None → idle backlog promotion disabled
    branch_prefix: str = "agent"
    commit_prefix: str = "agent"
    bot_name: str = "understudy-bot"
    bot_email: str = "understudy-bot@localhost"


def _require(d, key):
    if not isinstance(d, dict) or key not in d:
        raise ConfigError(f"config missing required key: {key}")
    return d[key]


def load_config(path):
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")

    target_repo = os.path.expanduser(_require(data, "target_repo"))
    dirs = _require(data, "dirs")
    gate = _require(data, "gate")

    def repo_path(rel):
        rel = os.path.expanduser(rel)
        return rel if os.path.isabs(rel) else os.path.join(target_repo, rel)

    naming = data.get("naming", {}) or {}

    return Config(
        target_repo=target_repo,
        queue_dir=repo_path(_require(dirs, "queue")),
        inbox_dir=repo_path(_require(dirs, "inbox")),
        worktrees_dir=os.path.expanduser(_require(dirs, "worktrees")),
        endpoint=_require(data, "endpoint"),
        models=_require(data, "models"),
        fallback=data.get("fallback", {"enabled": False, "model": ""}),
        gate=GateConfig(
            setup_cmd=gate.get("setup_cmd", ""),
            test_cmd=gate.get("test_cmd", ""),
            lint_cmd=gate.get("lint_cmd", ""),
            typecheck_cmd=gate.get("typecheck_cmd", ""),
            sandbox=_require(gate, "sandbox"),
            timeout=int(gate.get("timeout", 300)),
        ),
        max_parallel=int(data.get("max_parallel", 1)),
        home=os.path.expanduser("~"),
        backlog_dir=repo_path(dirs["backlog"]) if "backlog" in dirs else None,
        branch_prefix=naming.get("branch_prefix", "agent"),
        commit_prefix=naming.get("commit_prefix", "agent"),
        bot_name=naming.get("bot_name", "understudy-bot"),
        bot_email=naming.get("bot_email", "understudy-bot@localhost"),
    )
