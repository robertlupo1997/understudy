"""Parse/validate/claim queue task specs (spec §5). PyYAML safe_load only."""
import glob
import os
import re
import tempfile
from dataclasses import dataclass

import yaml

COMPLEXITIES = {"simple", "complex"}
AUTHORS = {"claude", "worker"}
STATUSES = {"queued", "running", "done", "failed", "needs_human"}

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


class QueueError(Exception):
    """Malformed or invalid queue task spec."""


@dataclass
class Task:
    id: str
    title: str
    complexity: str
    check_author: str
    check_cmd: str
    target_files: list
    status: str
    context: str
    prose: str
    path: str


def _split_frontmatter(text):
    m = _FRONTMATTER.match(text)
    if not m:
        raise QueueError("no YAML frontmatter (expected leading '---' block)")
    return m.group(1), m.group(2)


def parse_task(path):
    with open(path) as f:
        text = f.read()
    fm, prose = _split_frontmatter(text)
    data = yaml.safe_load(fm)
    if not isinstance(data, dict):
        raise QueueError(f"{path}: frontmatter is not a mapping")
    for key in ("id", "title", "complexity", "check_author", "check_cmd",
                "target_files", "status"):
        if key not in data:
            raise QueueError(f"{path}: missing required key '{key}'")
    if data["complexity"] not in COMPLEXITIES:
        raise QueueError(f"{path}: complexity must be one of {COMPLEXITIES}")
    if data["check_author"] not in AUTHORS:
        raise QueueError(f"{path}: check_author must be one of {AUTHORS}")
    if data["status"] not in STATUSES:
        raise QueueError(f"{path}: status must be one of {STATUSES}")
    tf = data["target_files"]
    if not isinstance(tf, list) or not tf:
        raise QueueError(f"{path}: target_files must be a non-empty list")
    return Task(
        id=str(data["id"]),
        title=str(data["title"]),
        complexity=data["complexity"],
        check_author=data["check_author"],
        check_cmd=str(data["check_cmd"]),
        target_files=[str(x) for x in tf],
        status=data["status"],
        context=str(data.get("context", "")),
        prose=prose,
        path=path,
    )


def list_queued(queue_dir):
    tasks = []
    for p in sorted(glob.glob(os.path.join(queue_dir, "*.md"))):
        try:
            t = parse_task(p)
        except QueueError as e:
            # A poison queue file must not kill the daemon's scan (callers:
            # run_once, maintenance.promote_next). parse_task stays strict.
            print(f"[queue] skipping malformed queue file {p}: {e}")
            continue
        if t.status == "queued":
            tasks.append(t)
    return sorted(tasks, key=lambda t: t.id)


def set_status(task, status):
    if status not in STATUSES:
        raise QueueError(f"unknown status: {status}")
    with open(task.path) as f:
        text = f.read()
    new, n = re.subn(r"(?m)^status:.*$", f"status: {status}", text, count=1)
    if n != 1:
        raise QueueError(f"{task.path}: no status line to update")
    d = os.path.dirname(task.path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as out:
            out.write(new)
        os.replace(tmp, task.path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    task.status = status
