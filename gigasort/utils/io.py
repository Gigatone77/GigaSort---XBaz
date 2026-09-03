"""Local I/O helpers: atomic JSON persistence and raw-key terminal input."""

import json
import os
import select
import sys
import tempfile

try:
    import termios
    import tty
    _TTY_OK = True
except Exception:  # pragma: no cover
    _TTY_OK = False


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


# ---------------------------------------------------------------------------
# raw-key input (used by the interactive screens; falls back to line input)
# ---------------------------------------------------------------------------
_ALIAS = {}
_ESC_seqs = {}


def _read_key():
    """Low-level single raw keypress via termios/tty. Falls back to a line."""
    if not _TTY_OK:
        try:
            return input()
        except EOFError:
            return ""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def read_key():
    """Return a semantic token: arrows->k/j/h/l, tab/enter/esc, ctrl-d, or a
    printable char. Drains trailing bytes of escape sequences."""
    global _ESC_seqs
    ch = _read_key()
    if not ch:
        return "esc"
    if ch == "\x1b":
        # read a follow-up byte to classify arrow keys etc.
        if _TTY_OK and _key_available(0.05):
            seq = ch + _read_key()
            if _key_available(0.05):
                seq += _read_key()
            return _ESC_seqs.get(seq, "esc")
        return "esc"
    if ch == "\x03" or ch == "\x1b":
        return "esc"
    if ch == "\n":
        return "\r"
    return ch


def _key_available(timeout):
    try:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return bool(r)
    except (OSError, ValueError):
        return False
