"""Interactive workspace setup (--setup). Persists settings in
_GigaSort_settings.json: target folder + extract-on-sort toggle."""

import os
import sys

from gigasort.constants import SETTINGS_FILENAME
from gigasort.core import storage


def run_setup(folder):
    settings = storage.load_settings(folder)

    print("== GigaSort setup  (workspace: %s) ==" % folder)

    target = settings.get("target_folder") or folder
    if sys.stdin.isatty():
        ans = input("Target mod folder [%s]: " % target).strip()
        if ans:
            target = os.path.abspath(os.path.expanduser(ans))
    settings["target_folder"] = target

    cur = bool(settings.get("extract_on_sort", True))
    if sys.stdin.isatty():
        ans = input("Extract archives on sort? %s [Y/n]: "
                    % ("yes" if cur else "no")).strip().lower()
        settings["extract_on_sort"] = ans not in ("n", "no")
    else:
        settings["extract_on_sort"] = cur

    storage.save_settings(folder, settings)
    print("Saved %s" % os.path.join(folder, SETTINGS_FILENAME))
    return 0
