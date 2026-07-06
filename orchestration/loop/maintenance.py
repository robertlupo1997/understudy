"""Idle Option-C task generation (spec §4/§8): when the queue is empty, promote
the next pre-authored task spec from the backlog into the queue.

Backlog items are authored by Claude at planning time (context-carrying specs,
spec §5) — maintenance only PROMOTES them. It never writes or edits a spec, so
the planning burst stays the sole source of task content (token contract +
check-provenance both depend on this)."""
import glob
import os

from orchestration.loop import queue


def promote_next(config):
    """Move the next valid queued backlog item into the queue.

    Returns the promoted task id, or None when: the queue still has queued
    work, no backlog is configured (backlog_dir None / missing), or nothing
    in the backlog is promotable. Malformed items are skipped with a log line
    (never crash the daemon); an item whose filename already exists in the
    queue is skipped (never clobber)."""
    if not config.backlog_dir or not os.path.isdir(config.backlog_dir):
        return None
    if queue.list_queued(config.queue_dir):
        return None
    for path in sorted(glob.glob(os.path.join(config.backlog_dir, "*.md"))):
        try:
            task = queue.parse_task(path)
        except queue.QueueError as e:
            print(f"[maintenance] skipping malformed backlog item {path}: {e}")
            continue
        if task.status != "queued":
            continue
        dst = os.path.join(config.queue_dir, os.path.basename(path))
        if os.path.exists(dst):
            print(f"[maintenance] queue already has {os.path.basename(path)}; skipping")
            continue
        os.makedirs(config.queue_dir, exist_ok=True)
        os.replace(path, dst)
        print(f"[maintenance] promoted {task.id} from backlog")
        return task.id
    return None
