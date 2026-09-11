"""Extract — unpack archives into per-mod folders (with meta.ini)."""

import os
import shutil
import zipfile

from gigasort.core.categorize import extract_mod_id
from gigasort.core.storage import scratch_dir


def _mod_folder_name(filename):
    """Folder name for an extracted mod: human name + id when available."""
    base = os.path.splitext(os.path.basename(filename))[0]
    mid = extract_mod_id(filename)
    return "%s-%s" % (base, mid) if mid else base


def extract_archive(path, out_dir, folder_for_stage=None):
    """Extract one archive into `out_dir`. Returns the created folder on
    success, else None (collision-safe: writes to a temp dir, then renames)."""
    import tempfile
    base = os.path.basename(path)
    out_dir = os.path.abspath(out_dir)
    name = _mod_folder_name(base)
    target = os.path.join(out_dir, name)

    tmp = tempfile.mkdtemp(prefix=".gigs-extract-", dir=out_dir)
    try:
        ext = os.path.splitext(base)[1].lower()
        if ext == ".zip":
            _unzip(path, tmp)
        else:
            _untar_like(path, tmp, ext)
        _write_meta(path, tmp, base)
        # flatten a single wrapping dir
        entries = sorted(os.listdir(tmp))
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
            wrapped = os.path.join(tmp, entries[0])
            if os.path.exists(target):
                shutil.rmtree(tmp, ignore_errors=True)
                return None
            shutil.move(wrapped, target)
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            if os.path.exists(target):
                shutil.rmtree(tmp, ignore_errors=True)
                return None
            shutil.move(tmp, target)
        return target
    except Exception:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        return None


def _unzip(path, dest):
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            member = info.filename
            target = os.path.normpath(os.path.join(dest, member))
            if not target.startswith(os.path.realpath(dest)):
                continue  # zip-slip guard
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def _untar_like(path, dest, ext):
    """7z/rar fallback: extract using external unar/7z binaries if present."""
    exe = shutil.which("7z") or shutil.which("7zz") or shutil.which("unar")
    if not exe:
        raise RuntimeError("no 7z/unar binary available for %s" % ext)
    import subprocess
    cmd = [exe, "x", "-y", "-o" + dest, path] if "7z" in exe.split("/")[-1] \
        else [exe, "-o", dest, path]
    subprocess.run(cmd, capture_output=True, check=False)


def _write_meta(path, dest, source_name):
    """Write a meta.ini alongside the mod so GigaSort can re-identify it."""
    mid = extract_mod_id(source_name)
    meta_path = os.path.join(dest, "GigaSort.meta.ini")
    try:
        from datetime import datetime
        with open(meta_path, "w", encoding="utf-8") as fh:
            fh.write("[GigaSort]\n")
            fh.write("source_file = %s\n" % source_name)
            fh.write("nexus_id = %s\n" % (mid or ""))
            fh.write("extracted = %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except OSError:
        pass


def extract_workspace(folder, force=False, only=None):
    """Extract every archive in the workspace into per-mod folders.

    Output lives in the centralized per-workspace scratch (never inside the
    workspace), consumed by --gamestructure. only: optional list of
    filenames. Returns (ok, failed) lists."""
    stage = scratch_dir(folder)
    os.makedirs(stage, exist_ok=True)
    ok, failed = [], []
    archives = sorted((n for n in os.listdir(folder)
                       if n.lower().endswith((".zip", ".rar", ".7z"))),
                      key=lambda n: n.lower())
    for name in archives:
        if only and name not in only:
            continue
        path = os.path.join(folder, name)
        dest = extract_archive(path, stage)
        if dest:
            ok.append(name)
        else:
            failed.append(name)
    return ok, failed


def list_extracted(folder):
    stage = scratch_dir(folder)
    if not os.path.isdir(stage):
        return []
    return sorted(n for n in os.listdir(stage)
                  if os.path.isdir(os.path.join(stage, n))
                  and os.path.exists(os.path.join(stage, n, "GigaSort.meta.ini")))


def run_extract(folder, input_fn=None, force=False, only=None):
    """High-level extract entry (GUI/CLI). Returns (ok, failed) file lists."""
    return extract_workspace(folder, force=force, only=only)