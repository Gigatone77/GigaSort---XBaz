"""FOMODPacker — activate and customize real FOMOD installers.

Cyberpunk 2077 mods on Nexus increasingly ship as FOMOD installers: the
archive contains a fomod/ModuleConfig.xml describing install *steps*, each
step exposing *groups* of mutually-exclusive (or select-any) *plugins* that
map source files inside the archive to game-relative destinations.

GigaSort detects FOMOD archives automatically and routes them into the
_FOMODS staging bin during scan, where they wait until you customize them.

This module handles the customization:

  1. detect FOMOD archives (zip with fomod/ModuleConfig.xml)
  2. parse ModuleConfig.xml (classic FOMM <config> and C#/<fomod> variants,
     UTF-8 or UTF-16 LE; tolerant of bare &nbsp; entities)
  3. list every step/group/plugin with preview image path so the user can
     make informed choices
  4. build a game-shaped tree under
     "<workspace>/FOMODPacker <ModName> - GAME STRUCTURE/" using the
     FOMOD's own source→destination mapping for the chosen plugins,
     honouring condition/dependancy flags exactly like the installer

Output is staging-only: files are written under the workspace root,
NEVER into the game install. Selection is passed as a JSON picks file:
    {"<step>": {"<group>": ["<plugin>", ...]}, ...}

The output folder carries a MOD_LIST.txt and a FOMODPacker.json manifest
recording archive name, module name, picks, extracted files, and any
issues encountered during flag evaluation.
"""

import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

FOMOD_MARK = "FOMODPacker"
FOMOD_MANIFEST = "_FOMODPacker.json"
MODULE_CONFIG = "fomod/ModuleConfig.xml"
MODULE_CONFIG_TXT = "fomod/ModuleConfig.txt"

_HTML_ENTITY_RE = re.compile(r"&([a-zA-Z0-9]+);")

_SELECT_ONE = ("SelectExactlyOne", "SelectOne", "SelectAtMostOne")
_SELECT_ANY = ("SelectAny", "SelectMany")
_SELECT_ALL = ("SelectAll",)


class FomodError(Exception):
    pass


# ---------------------------------------------------------------------------
# Detection / parsing
# ---------------------------------------------------------------------------

def is_fomod(path):
    """True when the archive carries a FOMOD ModuleConfig file."""
    try:
        if not path.lower().endswith(".zip"):
            return False
        import zipfile
        with zipfile.ZipFile(path) as zf:
            names = {n.replace("\\", "/").lower() for n in zf.namelist()}
        return any(n in names for n in
                   (MODULE_CONFIG.lower(), MODULE_CONFIG_TXT.lower()))
    except (zipfile.BadZipFile, OSError):
        return False


def _module_config_bytes(path):
    """Read the ModuleConfig payload from zip or rar/7z."""
    if path.lower().endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(path) as zf:
            for member in (MODULE_CONFIG, MODULE_CONFIG_TXT):
                try:
                    return zf.read(member)
                except KeyError:
                    continue
        raise FomodError("no fomod/ModuleConfig in %s" % os.path.basename(path))

    exe = shutil.which("7z") or shutil.which("7zz")
    if not exe:
        raise FomodError("rar/7z FOMOD needs the 7z binary")
    import subprocess
    with tempfile.TemporaryDirectory(prefix="gs-fomodp-") as tmp:
        subprocess.run([exe, "x", "-y", "-o" + tmp, path],
                       capture_output=True, check=False)
        for name in (MODULE_CONFIG, MODULE_CONFIG_TXT):
            p = os.path.join(tmp, *name.split("/"))
            if os.path.isfile(p):
                with open(p, "rb") as fh:
                    return fh.read()
        raise FomodError("no fomod/ModuleConfig in %s" % os.path.basename(path))


def _decode(raw):
    """Decode ModuleConfig XML: UTF-16 LE/BE BOM, UTF-8, or declared."""
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le", errors="replace")
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace")
    decl = re.match(rb"^\s*<\?xml[^>]*encoding=[\"']([\w-]+)[\"']", raw)
    if decl:
        try:
            return raw.decode(decl.group(1).decode("ascii"), errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    return raw.decode("utf-8", errors="replace")


def _parse_xml(text):
    """Parse with a tolerant parser (FOMODs love bare &nbsp; entities).

    Named references outside the XML 1.0 core set (amp/lt/gt/quot/apos)
    are normalized to numeric character references first so the stdlib
    parser accepts them on any Python version.
    """
    import html as _html

    def _entity(m):
        name = m.group(1)
        if name in ("amp", "lt", "gt", "quot", "apos"):
            return m.group(0)
        cp = _html.entities.html5.get("&%s;" % name)
        if cp and len(cp) == 1:
            return "&#%d;" % ord(cp)
        return " "

    text = _HTML_ENTITY_RE.sub(_entity, text)
    return ET.fromstring(text)


def _unname(el):
    return el.tag.rsplit("}", 1)[-1]


def parse_module_config(path):
    """Parse a FOMOD archive into {'moduleName', 'steps': [...]}.

    steps: [{'name', 'groups': [{'name','type','plugins':[
      {'name','description','image','files':[(src,dst,prio)],
       'set_flags':{flag:val}, 'need_flags':{flag:val},
       'type': 'Recommended'|'Optional'|...}]}]}]
    """
    raw = _module_config_bytes(path)
    root = _parse_xml(_decode(raw))

    config = root
    if _unname(root) != "config":
        for child in root.iter():
            if _unname(child) in ("ModuleSteps", "installSteps"):
                config = child
                break

    module_name = ""
    for el in root.iter():
        if _unname(el) == "moduleName" and el.text and el.text.strip():
            module_name = el.text.strip()
            break

    steps = []
    for step_el in config.iter():
        if _unname(step_el) != "installStep":
            continue
        groups = []
        for filegrp in step_el.iter():
            if _unname(filegrp) != "group":
                continue
            plugins = []
            for plug in filegrp.iter():
                if _unname(plug) != "plugin":
                    continue
                desc, image = "", ""
                set_flags, need_flags, files = {}, {}, []
                ptype = ""

                for child in plug.iter():
                    tag = _unname(child)
                    if tag == "description" and child.text:
                        desc = child.text.strip()
                    elif tag == "image":
                        image = (child.get("path") or "").replace("\\", "/")
                    elif tag == "type" and child.get("name"):
                        ptype = child.get("name")
                    elif tag == "file":
                        src = (child.get("source") or "").replace("\\", "/")
                        dst = (child.get("destination") or "").replace("\\", "/")
                        prio = int(child.get("priority") or 0)
                        if src and dst:
                            files.append((src, dst, prio))
                    elif tag == "folder":
                        src = (child.get("source") or "").replace("\\", "/")
                        dst = (child.get("destination") or "").replace("\\", "/")
                        if src:
                            files.append((src.rstrip("/"),
                                         dst.rstrip("/") or os.path.basename(src),
                                         0))

                # walk conditionFlags / dependancyFlags
                for flag_el in plug.iter():
                    if _unname(flag_el) != "flag" or not flag_el.get("name"):
                        continue
                    key = flag_el.get("name")
                    val = (flag_el.text or flag_el.get("value") or "on").strip()
                    for parent in plug.iter():
                        pt = _unname(parent)
                        if pt in ("conditionFlags",) and \
                           _contains(parent, flag_el):
                            set_flags[key] = val
                            break
                        elif pt in ("dependancyFlags", "dependencyFlags") and \
                             _contains(parent, flag_el):
                            need_flags[key] = val
                            break

                plugins.append({
                    "name": (plug.get("name") or "").strip(),
                    "description": desc,
                    "image": image,
                    "type": ptype,
                    "files": files,
                    "set_flags": set_flags,
                    "need_flags": need_flags,
                })
            if plugins:
                groups.append({
                    "name": (filegrp.get("name") or "group").strip(),
                    "type": (filegrp.get("type") or "SelectAny").strip(),
                    "plugins": plugins,
                })
                plugins = []
        if groups:
            steps.append({
                "name": (step_el.get("name") or
                         (step_el.findtext("visibleName") or "").strip() or
                         "step %d" % (len(steps) + 1)),
                "groups": groups,
            })
    return {"moduleName": module_name, "steps": steps}


def _contains(parent, node):
    for el in parent.iter():
        if el is node:
            return True
    return False


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def describe(path, picks=None):
    """Human-readable listing of every step/group/plugin choice."""
    meta = parse_module_config(path)
    lines = ["%s — %s" % (os.path.basename(path), meta["moduleName"])]
    for si, step in enumerate(meta["steps"]):
        lines.append("\nstep %d: %s" % (si + 1, step["name"]))
        for group in step["groups"]:
            picked = picks.get(step["name"], {}).get(group["name"]) if picks \
                else None
            lines.append("   group: %s  [%s]" % (group["name"], group["type"]))
            for plugin in group["plugins"]:
                mark = " <- PICKED" if picked and plugin["name"] in picked \
                    else ""
                lines.append("      [%s] %s%s" % (
                    plugin.get("type") or "Optional",
                    plugin["name"], mark))
                if plugin["image"]:
                    lines.append("        img: %s" % plugin["image"])
                if plugin["description"]:
                    lines.append("        %s" % _one_line(plugin["description"]))
    return "\n".join(lines)


def _one_line(text):
    return re.sub(r"\s+", " ", text).strip()[:160]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(path, picks, workspace, dry_run=False, force_overwrite=True):
    """Resolve a FOMOD against picks and stage the chosen game tree.

    Returns {'root', 'module', 'files', 'steps', 'issues'}."""
    meta = parse_module_config(path)
    module = meta["moduleName"] or os.path.splitext(
        os.path.basename(path))[0]
    out_root = os.path.join(workspace, "%s %s - GAME STRUCTURE"
                            % (FOMOD_MARK, module))
    issues = []

    if not dry_run and force_overwrite:
        shutil.rmtree(out_root, ignore_errors=True)
    if not dry_run:
        os.makedirs(out_root, exist_ok=True)

    # Step 1: select plugins, apply flags like the installer.
    chosen = []
    flags = {}
    for step in meta["steps"]:
        for group in step["groups"]:
            try:
                sel = _select_plugins(group, step, picks, flags)
            except FomodError as exc:
                issues.append("[%s/%s] %s" % (step["name"], group["name"], exc))
                sel = []
            for plugin in sel:
                chosen.append((plugin, step, group))
                for key, val in plugin["set_flags"].items():
                    flags[key] = val

    # Step 2: collect file bindings, highest priority wins.
    bindings = []
    for plugin, _step, _group in chosen:
        for src, dst, prio in plugin["files"]:
            bindings.append((dst, src, prio))

    best = {}
    for dst, src, prio in bindings:
        prev = best.get(dst)
        if prev is None or prio >= prev[1]:
            best[dst] = (src, prio)
    bindings = [(dst, src_prio[0]) for dst, src_prio in best.items()]

    # Step 3: extract.
    if not dry_run:
        _extract_bindings(path, bindings, out_root)

    summary = {}
    for plugin, step, _group in chosen:
        summary.setdefault(step["name"], []).append(plugin["name"])

    return {
        "root": out_root,
        "module": module,
        "files": len(bindings),
        "steps": summary,
        "issues": issues,
    }


def _select_plugins(group, step, picks, flags):
    gtype = group["type"]
    allowed = [p for p in group["plugins"]
               if all(flags.get(k, "").lower() == v.lower()
                      for k, v in p["need_flags"].items())]

    picked_names = []
    if picks:
        step_pick = picks.get(step["name"]) or {}
        picked_names = step_pick.get(group["name"]) or []

    if gtype in _SELECT_ALL:
        return allowed
    if gtype in _SELECT_ONE:
        if picked_names:
            hit = [p for p in allowed if p["name"] in picked_names]
            if len(hit) == 1:
                return hit
            raise FomodError("SelectExactlyOne requires 1 valid pick, got %s"
                             % picked_names)
        return allowed[:1]
    # SelectAny
    if not picked_names:
        return []
    out = []
    for name in picked_names:
        hit = [p for p in allowed if p["name"] == name]
        if hit:
            out.append(hit[0])
        else:
            raise FomodError("unknown/blocked plugin %r" % name)
    return out


def _extract_bindings(path, bindings, out_root):
    if path.lower().endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(path) as zf:
            seen = set()
            for dst, src in bindings:
                member = src.replace("\\", "/")
                if member in seen:
                    continue
                seen.add(member)
                try:
                    info = zf.getinfo(member)
                except KeyError:
                    continue
                if info.is_dir():
                    continue
                target = os.path.join(out_root, *dst.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                if os.path.exists(target):
                    continue
                shutil.copyfileobj(zf.open(info), open(target, "wb"))
        return

    exe = shutil.which("7z") or shutil.which("7zz")
    if not exe:
        raise FomodError("rar/7z FOMOD needs the 7z binary")
    with tempfile.TemporaryDirectory(prefix="gs-fomodp-") as tmp:
        import subprocess
        subprocess.run([exe, "x", "-y", "-o" + tmp, path],
                       capture_output=True, check=False)
        for dst, src in bindings:
            src_host = os.path.join(tmp, *src.split("/"))
            if not os.path.isfile(src_host):
                continue
            dst_host = os.path.join(out_root, *dst.split("/"))
            os.makedirs(os.path.dirname(dst_host), exist_ok=True)
            shutil.copy2(src_host, dst_host)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def write_manifest(build_result, archive, picks):
    manifest = {
        "tool": FOMOD_MARK,
        "source_archive": os.path.basename(archive),
        "module": build_result["module"],
        "output_root": build_result["root"],
        "files": build_result["files"],
        "picks": picks,
        "steps": build_result["steps"],
        "issues": build_result["issues"],
    }
    path = os.path.join(build_result["root"], FOMOD_MANIFEST)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)


def write_modlist(build_result):
    modlist = "%s — %s\n%s\n\nPicks:\n%s\n" % (
        FOMOD_MARK,
        build_result["module"],
        "=" * (len(FOMOD_MARK) + len(build_result["module"]) + 5),
        json.dumps(build_result["steps"], indent=2))
    if build_result["issues"]:
        modlist += "\nIssues:\n" + "\n".join(build_result["issues"]) + "\n"
    path = os.path.join(build_result["root"], "MOD_LIST.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(modlist)