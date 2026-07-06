import json
import os
import shutil
import subprocess
import textwrap
import urllib.request
import pytest
from orchestration.loop import run_loop
from orchestration.loop import config as cfg
from orchestration.loop.tests.conftest import write_config_yaml

pytestmark = pytest.mark.sandbox            # live worker + bwrap; excluded from the no-regression leg


def _ollama_up(endpoint):
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + "/models", timeout=3) as r:
            return getattr(r, "status", 200) == 200
    except OSError:
        return False


run_e2e = pytest.mark.skipif(
    os.environ.get("UNDERSTUDY_E2E") != "1" or shutil.which("bwrap") is None,
    reason="set UNDERSTUDY_E2E=1 and install bwrap to run the live end-to-end test")


@run_e2e
def test_live_loop_produces_gated_diff(temp_repo, tmp_path):
    # Claude-authored check committed into base
    (temp_repo / "test_add.py").write_text(
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run(["git", "-C", str(temp_repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(temp_repo), "commit", "-qm", "check"], check=True)

    c = cfg.load_config(str(write_config_yaml(tmp_path / "config.yaml", temp_repo)))
    if not _ollama_up(c.endpoint):
        pytest.skip("Ollama endpoint not reachable")

    os.makedirs(c.queue_dir, exist_ok=True)
    with open(os.path.join(c.queue_dir, "t1.md"), "w") as f:
        f.write(textwrap.dedent("""\
            ---
            id: t1
            title: "add(a, b)"
            complexity: simple
            check_author: claude
            check_cmd: "python3 -m pytest test_add.py -q"
            target_files: [add.py]
            status: queued
            context: |
              Write a Python module defining add(a, b) that returns a + b. stdlib only.
            ---
            Implement add(a, b) returning the sum.
            """))

    n = run_loop.run_once(c)                     # real worker -> real Ollama -> real gate
    assert n == 1
    meta = json.load(open(os.path.join(c.inbox_dir, "t1", "meta.json")))
    assert meta["status"] in ("passed", "failed")     # gated either way; never silently dropped
    assert os.path.isfile(os.path.join(c.inbox_dir, "t1", "diff.patch"))
    # base untouched (propose-only)
    log = subprocess.run(["git", "-C", str(temp_repo), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "add(a, b)" not in log                      # nothing merged into the working branch
