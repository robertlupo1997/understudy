import textwrap
import pytest
from orchestration.loop import config as cfg
from orchestration.loop.tests.conftest import write_config_yaml


def test_load_resolves_paths_and_gate(tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    p = write_config_yaml(tmp_path / "config.yaml", repo, test_cmd="python3 -m pytest -q")
    c = cfg.load_config(str(p))
    assert c.target_repo == str(repo)
    assert c.queue_dir == str(repo / "queue")           # dirs.queue is relative to target_repo
    assert c.inbox_dir == str(repo / "inbox")
    assert c.gate.test_cmd == "python3 -m pytest -q"
    assert c.gate.timeout == 60
    assert c.models["simple"] == "ornith9b"
    assert c.max_parallel == 1
    assert c.home  # non-empty expanded home


def test_missing_required_key_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("dirs: {queue: q, inbox: i, worktrees: w}\n")   # no target_repo
    with pytest.raises(cfg.ConfigError):
        cfg.load_config(str(p))


def test_non_mapping_yaml_raises(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- 1\n- 2\n")
    with pytest.raises(cfg.ConfigError):
        cfg.load_config(str(p))


def test_backlog_dir_resolves_when_present(tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", repo)))
    assert c.backlog_dir == str(repo / "backlog")       # conftest emits dirs.backlog: backlog


def test_backlog_dir_defaults_to_none(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent("""\
        target_repo: /tmp/x
        dirs: {queue: q, inbox: i, worktrees: w}
        endpoint: http://localhost:11434/v1
        models: {simple: a, complex: b}
        gate: {sandbox: "true", timeout: 5}
    """))
    c = cfg.load_config(str(p))
    assert c.backlog_dir is None


def test_naming_defaults_and_override(tmp_path):
    from orchestration.loop import config as cfg
    p = tmp_path / "c.yaml"
    p.write_text(
        "target_repo: /tmp/r\n"
        "dirs: {queue: q, inbox: i, worktrees: w}\n"
        "endpoint: http://x/v1\n"
        "models: {simple: m, complex: m}\n"
        "gate: {sandbox: 'true'}\n")
    c = cfg.load_config(str(p))
    assert (c.branch_prefix, c.commit_prefix) == ("agent", "agent")
    assert c.bot_name == "understudy-bot" and c.bot_email == "understudy-bot@localhost"
    p.write_text(p.read_text() + "naming: {branch_prefix: wip, bot_name: bot}\n")
    c2 = cfg.load_config(str(p))
    assert c2.branch_prefix == "wip" and c2.bot_name == "bot"
