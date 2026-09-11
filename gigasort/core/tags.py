"""Tags — user-added labels attached to workspace files."""


from gigasort.core.storage import load_tags, save_tags

# A small fixed vocabulary the GUI offers as chips.
KNOWN_TAGS = ("setup-needed", "risky", "review", "favorite", "broken",
              "nsfw", "test")

# Keywords that map a filename to a KNOWN_TAG suggestion.
AUTO_TAGS = {
    "risky": ("beta", "unstable", "ai", "experimental"),
    "nsfw": ("nud", "sex", "nsfw", "porn"),
    "favorite": ("sticky", "favorite"),
    "setup-needed": ("reinstall", "config", "instructions"),
}


def tag_file(folder, filename, *tags, replace=False):
    d = load_tags(folder)
    cur = d.get(filename) or []
    if replace:
        cur = list(tags)
    else:
        for t in tags:
            if t not in cur:
                cur.append(t)
    d[filename] = cur
    save_tags(folder, d)


def untag_file(folder, filename, *tags):
    d = load_tags(folder)
    cur = d.get(filename) or []
    for t in tags:
        if t in cur:
            cur.remove(t)
    if cur:
        d[filename] = cur
    else:
        d.pop(filename, None)
    save_tags(folder, d)


def file_tags(folder, filename):
    return load_tags(folder).get(filename) or []


def suggest_tags(filename):
    low = filename.lower()
    out = []
    for tag, keys in AUTO_TAGS.items():
        if any(k in low for k in keys):
            out.append(tag)
    return out


def all_tagged(folder):
    return {k: v for k, v in load_tags(folder).items()}


def write_tags(folder):
    """Persist the tags file (idempotent; called after a successful apply)."""
    save_tags(folder, load_tags(folder))