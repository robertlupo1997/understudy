import os
import subprocess
import textwrap
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "sandbox: spawns bwrap or needs ambient git/HOME; excluded from the "
        "in-sandbox no-regression leg (config test_cmd uses -m 'not sandbox')")


SANDBOX = (
    # Mount order matters: every --tmpfs must precede the --ro-bind {worktree}
    # rebind, or a worktree under /tmp (tmp_path) or $HOME gets shadowed. Do not reorder.
    "bwrap --ro-bind / / --tmpfs {home} --tmpfs /tmp "
    "--ro-bind-try {home}/.local/lib {home}/.local/lib --ro-bind {worktree} {worktree} "
    "--dev /dev --proc /proc --unshare-all --die-with-parent "
    "--setenv PYTHONDONTWRITEBYTECODE 1 "
    "--setenv PYTEST_ADDOPTS '-p no:cacheprovider' --chdir {worktree}"
)


def write_config_yaml(path, target_repo, sandbox=SANDBOX, test_cmd="", timeout=60):
    """Write a config.yaml into `path` pointing at `target_repo`."""
    path.write_text(textwrap.dedent(f"""\
        target_repo: {target_repo}
        dirs:
          queue:     queue
          inbox:     inbox
          backlog:   backlog
          worktrees: {target_repo}/.wt
        endpoint: http://localhost:11434/v1
        models:
          simple:  ornith9b
          complex: ornith35b
        fallback:
          enabled: false
          model: haiku
        gate:
          setup_cmd: ""
          test_cmd: "{test_cmd}"
          lint_cmd: ""
          typecheck_cmd: ""
          sandbox: "{sandbox}"
          timeout: {timeout}
        max_parallel: 1
    """))
    return path


@pytest.fixture
def temp_repo(tmp_path):
    """A throwaway git repo on branch `work` (never `main`) with one base commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True, env=env).stdout

    git("init", "-q", "-b", "work")
    (repo / "README.md").write_text("base\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    return repo
