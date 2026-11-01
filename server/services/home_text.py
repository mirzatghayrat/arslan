"""The home folder in free text the phone is shown, as `~` (IPB: the #651 and #650 reviews): a task's title, a
connector's name. The absolute home path names the user, so it never leaves the Mac in these.

Only a whole path is replaced: home not right after an ASCII name or path character (but right after `://`, as
in `file:///Users/…`), and not followed by one, nor by a `.` that goes on into a name (`/Users/alice.old`); a
full stop ending a sentence is not part of the path. The classes are ASCII on purpose, so a path written right
against Chinese text (`把/Users/alice/Downloads里`) is still found. Letter case and Unicode form are ignored, as
the startup volume ignores them.
"""
from __future__ import annotations

import re
import unicodedata

_NAME = "A-Za-z0-9_"


def fold_home(text: str, home: str) -> str:
    """`text` (in NFC) with each whole-path occurrence of `home` as `~`; unchanged for a home of `/` or ``."""
    home = unicodedata.normalize("NFC", str(home or "")).rstrip("/")
    text = unicodedata.normalize("NFC", text or "")
    if not home:
        return text
    pattern = (rf"(?:(?<=://)|(?<![{_NAME}./~-]))" + re.escape(home)
               + rf"(?![{_NAME}~-]|\.[{_NAME}])")
    return re.sub(pattern, "~", text, flags=re.IGNORECASE)
