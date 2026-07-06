"""Count files in queue_dir by their status line."""

import glob
import os
import re


def count_by_status(queue_dir):
    """Return a dict mapping status strings to file counts from *.md files in queue_dir."""
    pattern = re.compile(r'^status:\s*(\S+)')
    result = {}
    for filepath in glob.glob(os.path.join(queue_dir, '*.md')):
        with open(filepath, 'r', encoding='utf-8') as f:
            first_match = None
            for line in f:
                m = pattern.match(line)
                if m is not None:
                    status = m.group(1)
                    result[status] = result.get(status, 0) + 1
                    break
    return result
