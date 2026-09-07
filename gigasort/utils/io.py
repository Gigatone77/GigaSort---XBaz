"""Local I/O helpers: atomic JSON persistence."""

import json
import os
import tempfile


def _atomic_write_text(path, text):
    """Write text to `path` atomically (tmp file in the same dir, then
    os.replace) so an interrupted run never leaves a half-written state file."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def json_load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def json_dump(path, data):
    _atomic_write_text(path, json.dumps(data, indent=2))
