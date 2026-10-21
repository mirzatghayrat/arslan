"""Arslan Hands' state in the backend (0.1.53): its switch and never-list, who
was asked about what, the Stop latch, the trace, and what counts as high-risk.

Settings live in `<data>/hands/settings.json` (not settings_service: 0.1.52 and
0.1.53 ship in parallel and must not collide). The built-in never-list and app
tiers come from `desktop/hands/policy.json` — the file the helper compiles in —
so Settings shows exactly the list Hands enforces. The backend can only add to
it (the user's own "never touch" entries); Hands enforces the built-in list on
its own side regardless of what the backend sends.

Asking goes through `permissions.decide` (0.1.61 §A11): one `app` card covers looking and acting,
"for this task" first; its grants and "Always" rules are the permission store's, not this module's.
What is risky (`app_risky`) or money (`money`) is decided here, and asks every time.
"""
from __future__ import annotations

import functools
import json
import os
import plistlib
import re
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TRACE_DAYS = 7
MAX_NEVER = 200

_lock = threading.Lock()
_sessions: dict[str, str] = {}                 # job id → agent-desktop session (cursor)
_stopped: set[str] = set()                     # job ids that were running at a Stop
# H3: chat turns (and scheduled runs) in flight at a Stop, by their desktop_status work id — a chat
# turn has no job id. A mark goes when its work ends (pruned against the work in flight).
_stopped_turns: set[int] = set()
_permission_asked = False


# ── settings ─────────────────────────────────────────────────────────────────

def _dir() -> Path:
    from server import config
    return Path(config.data_dir()) / "hands"


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def settings() -> dict:
    try:
        raw = json.loads((_dir() / "settings.json").read_text())
    except (OSError, ValueError):
        raw = {}
    never = raw.get("never") if isinstance(raw, dict) else None
    return {
        "enabled": bool(raw.get("enabled", True)) if isinstance(raw, dict) else True,
        "cursor": bool(raw.get("cursor", True)) if isinstance(raw, dict) else True,
        # Hands v2: a screenshot of the window with each look (spec §4.2); on unless turned off.
        "screenshots": bool(raw.get("screenshots", True)) if isinstance(raw, dict) else True,
        # Hands v2 §6.3: borrow the front for a moment when an action needs it (on by default).
        "borrow": bool(raw.get("borrow", True)) if isinstance(raw, dict) else True,
        # Hands v2 §6.5: while the user is away, a takeover starts without its card (off by default;
        # risky actions still wait for the user).
        "away": bool(raw.get("away", False)) if isinstance(raw, dict) else False,
        "never": [str(n)[:120] for n in never if isinstance(n, str) and n.strip()][:MAX_NEVER]
                 if isinstance(never, list) else [],
        # Hands v2 §7.2-7.4: apps allowed for good (looking and acting asked no more; risky steps still
        # ask every time), and apps whose windows are never screenshotted (read as text only).
        "always": _always(raw.get("always") if isinstance(raw, dict) else None),
        "no_screenshots": [str(n)[:120] for n in raw.get("no_screenshots") or [] if isinstance(n, str) and n.strip()][
            :MAX_NEVER] if isinstance(raw, dict) and isinstance(raw.get("no_screenshots"), list) else [],
    }


MAX_ALWAYS = 100


def _always(raw) -> list[dict]:
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and isinstance(item.get("bundle_id"), str) and item["bundle_id"].strip():
            out.append({"bundle_id": item["bundle_id"].strip()[:200], "name": str(item.get("name") or "")[:120],
                        "since": str(item.get("since") or "")[:40]})
    return out[:MAX_ALWAYS]


async def migrate_always() -> None:
    """0.1.61 §A5: the apps allowed for good in Settings → Hands (the `always` setting before 0.1.61)
    become `app` rules in the permission store, once; the setting is emptied afterwards, so the store
    is the only "Always" — what Settings lists, and what `permissions.decide` reads."""
    old = settings()["always"]
    if not old:
        return
    from server.db import session as db_session
    from server.services import permission_store
    async with db_session.AsyncSessionLocal() as db:
        for app in old:
            await permission_store.add_rule(db, "app", app["bundle_id"], label=app["name"] or app["bundle_id"],
                                            created_from="migration")
        await db.commit()
    update_settings(always=[])


async def always_apps() -> list[dict]:
    """The apps allowed for good (`app` rules), as Settings → Hands lists them."""
    from server.db import session as db_session
    from server.services import permission_store
    await migrate_always()
    async with db_session.AsyncSessionLocal() as db:
        rules = await permission_store.list_rules(db, "app")
    return [{"bundle_id": r.target, "name": r.label or r.target,
             "since": r.created_at.strftime("%Y-%m-%d") if r.created_at else ""} for r in rules]


async def allow_always(bundle_id: str, name: str) -> None:
    from server.db import session as db_session
    from server.services import permission_store
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_rule(db, "app", bundle_id, label=name or bundle_id, created_from="settings")
        await db.commit()


async def stop_always(bundle_id: str) -> None:
    from server.db import session as db_session
    from server.services import permission_store
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.delete_rule_by(db, "app", bundle_id)
        await db.commit()


def no_screenshots(name: str, bundle_id: str) -> bool:
    """§4.2: the user listed this app as never screenshotted (name or bundle id, any case)."""
    wanted = {name.strip().lower(), bundle_id.strip().lower()} - {""}
    return any(n.strip().lower() in wanted for n in settings()["no_screenshots"])


def update_settings(*, enabled: bool | None = None, cursor: bool | None = None,
                    never: list[str] | None = None, screenshots: bool | None = None,
                    borrow: bool | None = None, away: bool | None = None,
                    always: list[dict] | None = None, no_screenshots: list[str] | None = None) -> dict:
    current = settings()
    if always is not None:
        current["always"] = _always(always)
    if no_screenshots is not None:
        seen_names: list[str] = []
        for item in no_screenshots:
            item = " ".join(str(item).split())[:120]
            if item and item.lower() not in (n.lower() for n in seen_names):
                seen_names.append(item)
        current["no_screenshots"] = seen_names[:MAX_NEVER]
    if borrow is not None:
        current["borrow"] = bool(borrow)
    if away is not None:
        current["away"] = bool(away)
    if enabled is not None:
        current["enabled"] = bool(enabled)
    if screenshots is not None:
        current["screenshots"] = bool(screenshots)
    if cursor is not None:
        current["cursor"] = bool(cursor)
    if never is not None:
        seen: list[str] = []
        for item in never:
            item = " ".join(str(item).split())[:120]
            if item and item.lower() not in (s.lower() for s in seen):
                seen.append(item)
        current["never"] = seen[:MAX_NEVER]
    folder = _private_dir(_dir())
    tmp = folder / "settings.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(current, f)
    os.replace(tmp, folder / "settings.json")
    return current


# ── the shared policy file ───────────────────────────────────────────────────

def _policy_path() -> Path:
    server_dir = Path(__file__).resolve().parent.parent
    packaged = server_dir / "resources" / "hands" / "policy.json"     # PyInstaller datas
    return packaged if packaged.is_file() else server_dir.parent / "desktop" / "hands" / "policy.json"


def policy() -> dict:
    return json.loads(_policy_path().read_text())


_TEAM_PREFIX = re.compile(r"^[A-Z0-9]{10}\.(?=.)")


def _matches(group: dict, bundle_id: str, name: str) -> bool:
    bundle_id = _TEAM_PREFIX.sub("", bundle_id)     # e.g. 2BUA8C4S2C.com.1password.browser-helper
    for pattern in group.get("bundle_ids", []):
        if pattern.endswith(".*"):
            prefix = pattern[:-2].lower()
            if bundle_id.lower() == prefix or bundle_id.lower().startswith(prefix + "."):
                return True
        elif bundle_id and bundle_id.lower() == pattern.lower():
            return True
    return any(n.lower() == name.strip().lower() for n in group.get("names", []))


# Where installed apps live (0.1.61 §A11): an app's name is turned into its bundle id from its own
# Info.plist, so a rule or the never-list can hold the bundle id while a script names the app.
_APP_DIRS = ("/Applications", "/Applications/Utilities", "/System/Applications",
             "/System/Applications/Utilities", "/System/Library/CoreServices",
             "/System/Library/CoreServices/Applications", "~/Applications")
_BUNDLE_ID = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


def _app_bundles_named(folder: Path, app: str) -> list[Path]:
    """`<app>.app` in `folder`, then any entry whose name matches it ignoring case: AppleScript takes an
    app's name in any case ("VAULT.APP" is Vault), and on a case-sensitive volume (and CI's Linux) the
    exact path alone missed it, so the never-list did too (v0.1.63 H4, found by CI on #271)."""
    exact = folder / f"{app}.app"
    found = [exact]
    try:
        wanted = f"{app}.app".casefold()
        found += sorted(p for p in folder.iterdir() if p.name.casefold() == wanted and p.name != exact.name)
    except OSError:
        pass
    return found


@functools.lru_cache(maxsize=256)
def app_identity(app: str) -> dict | None:
    """{"name", "bundle_id"} for an app name or bundle id, read from the installed app's Info.plist —
    never by launching it (`osascript -e 'id of app "X"'` would). A bundle id is taken as given. None
    when no installed app has that name and it is no bundle id. Running apps outside these folders are resolved by Hands
    (`which_app`) on the Hands path."""
    app = app.strip()
    if app.lower().endswith(".app"):
        app = app[:-4].strip()
    if not app or "/" in app:
        return None
    for folder in _APP_DIRS:
        for bundle_dir in _app_bundles_named(Path(folder).expanduser(), app):
            plist = bundle_dir / "Contents" / "Info.plist"
            try:
                with plist.open("rb") as f:
                    info = plistlib.load(f)
            except (OSError, plistlib.InvalidFileException, ValueError):
                continue
            bundle = str(info.get("CFBundleIdentifier") or "")
            if bundle:
                return {"name": str(info.get("CFBundleName") or app), "bundle_id": bundle}
    if _BUNDLE_ID.match(app):                     # no app has that name: it is a bundle id
        return {"name": "", "bundle_id": app}
    return None


_PATH_PARTS = re.compile(r"[/:]")
_MAX_INFO_PLIST = 1 << 20


def app_name(app: str) -> str:
    """The app an AppleScript means, as a name (v0.1.63 H4, found by ②Main): AppleScript takes
    "Finder", "Finder.app", a POSIX path to the bundle ("/System/Library/CoreServices/Finder.app") or
    an HFS one ("Macintosh HD:System:Library:CoreServices:Finder.app:") for the same app. The last
    path component, without a trailing ".app" in any case. A bundle id comes back as it is."""
    name = app.strip()
    if "/" in name or ":" in name:
        parts = [p.strip() for p in _PATH_PARTS.split(name) if p.strip()]
        name = parts[-1] if parts else ""
    if name.lower().endswith(".app"):
        name = name[:-4].strip()
    return name


def app_key(app: str) -> str:
    """`app_name` in lower case: what the never-list, the high-reach set and `script_apps` compare, so
    one app named three ways is one app."""
    return app_name(app).lower()


def _bundle_paths(text: str) -> list[Path]:
    """Where an app named by a path lives: a POSIX path as it is; an HFS path ("Macintosh
    HD:Applications:Notes.app:") on that volume under /Volumes and on the startup disk, both tried
    (②Main on #271: HFS paths were not read at all). Empty for a plain name or a bundle id."""
    if "/" in text:
        return [Path(text).expanduser()]
    if ":" not in text:
        return []
    parts = [p for p in text.strip(":").split(":") if p]
    if len(parts) < 2:
        return []
    return [Path("/Volumes", *parts), Path("/", *parts[1:])]


def _read_bundle_id(bundle: Path) -> str:
    """CFBundleIdentifier from a bundle's own Info.plist: a regular file under a size cap, nothing
    launched. "" when there is none."""
    if bundle.suffix.lower() != ".app":
        return ""
    plist = bundle / "Contents" / "Info.plist"
    try:
        if not plist.is_file() or plist.stat().st_size > _MAX_INFO_PLIST:
            return ""
        with plist.open("rb") as f:
            info = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return ""
    return str(info.get("CFBundleIdentifier") or "") if isinstance(info, dict) else ""


def _bundle_at(app: str) -> str:
    """The bundle id of an app named by a path to its bundle (POSIX, "~/…" or HFS), read from that
    bundle's own Info.plist — so a renamed bundle, or one outside the usual folders, is known by what
    it is, not by its file name. "" when the text is no path to an existing app bundle."""
    for bundle in _bundle_paths(app.strip()):
        if bundle_id := _read_bundle_id(bundle):
            return bundle_id
    return ""


def _bundles_of(app: str) -> set[str]:
    """Every bundle id `app` can mean: the bundle at its path, and the installed app with its name."""
    by_name = (app_identity(app_name(app)) or {}).get("bundle_id") or ""
    return {b for b in (_bundle_at(app), by_name) if b}


def never_touched(app: str) -> bool:
    """A name or bundle id on the built-in never-list or the user's own — matched by the name and by
    the bundle id of the installed app with that name (0.1.61 §A11), so a script that names an app
    and a rule that holds its bundle id see the same list. v0.1.63 H4: the name is `app_name`'s, so
    "1Password.app", "/Applications/1Password.app" and an HFS path are 1Password too; an app named by
    its path is also known by the bundle id inside it (a renamed copy is still refused)."""
    raw = app.strip()
    name = app_name(raw)
    bundles = _bundles_of(raw)
    keys = ({raw.lower(), name.lower()} | {b.lower() for b in bundles}) - {""}
    if any(n.strip().lower() in keys or app_key(n) in keys for n in settings()["never"]):
        return True
    return any(_matches(g, candidate, name) for g in policy()["denied"] for candidate in bundles | {raw})


# `tell application "X"`, `tell app "X"`, `application id "com.x"`, `using terms from application "X"`.
# Any length: AppleScript takes a long path as well as a short name, and a name this did not capture
# was never checked against the never-list (v0.1.63 H4: a path padded past 120 characters, "/Applications/
# ./././…/1Password.app", named no app here). The card trims what it shows; the check sees it whole.
# Matched on the code (`_mask`: comments and string insides blanked) and read back from the script at the
# same place, so the gap before the quote is whatever AppleScript takes: none at all (`application"X"`,
# which it compiles to `application "X"`) or a `¬` line continuation (⓪Plan, Opus 5.5, on #265/#271: both
# compiled, and `\s+` saw neither); and a word in a comment or a string is no app.
_SCRIPT_APP = re.compile(r'\b(?:application|app)[\s¬]*(?:id[\s¬]*)?"', re.I)


def _mask(script: str) -> str:
    """The script with its comments (`--`, `#`, nesting `(* … *)`) and the insides of its strings
    blanked to spaces, at the same length: what is left is code, every `"` still marks where a literal
    string stood, and a position in it is the same position in the script."""
    out, i, n, depth = list(script), 0, len(script), 0
    while i < n:
        two = script[i:i + 2]
        if depth or two == "(*":
            if two in ("(*", "*)"):
                depth += 1 if two == "(*" else -1
                out[i] = out[i + 1] = " "
                i += 2
                continue
            if script[i] != "\n":
                out[i] = " "
            i += 1
            continue
        if script[i] == '"':
            j = i + 1
            while j < n and script[j] != '"':
                step = 2 if script[j] == "\\" and j + 1 < n else 1
                for k in range(j, min(j + step, n)):
                    if script[k] != "\n":
                        out[k] = " "
                j += step
            i = j + 1
            continue
        if two == "--" or script[i] == "#":
            while i < n and script[i] != "\n":
                out[i] = " "
                i += 1
            continue
        i += 1
    return "".join(out)


_APP_WORD = re.compile(r"\b(?:application|app)\b", re.I)
_RAW_APP_CLASS = re.compile(r"«\s*class\s+capp\s*»", re.I)
# Spaces, and a `¬` continuation onto the next line; a plain line end ends the statement, so a class name
# at the end of a line (`tell current application`, `count processes`) is followed by nothing.
_GAP = re.compile(r"(?:[ \t]|¬[ \t]*\r?\n)*")
_WORD = re.compile(r"\|[^|\n]*\||[A-Za-z_][A-Za-z0-9_]*")
# What may follow `application` when it is a class name and not the app a script talks to: System
# Events' and Finder's classes, and the words a type test or a filter goes on with.
_NOT_A_TARGET = frozenset({
    "process", "processes", "file", "files", "then", "of", "in", "is", "whose", "where", "and", "or",
    "as", "else", "end", "to", "from", "by", "with", "without", "contains", "returning", "given", "not",
    "equals", "comes", "before", "after", "but", "thru", "through", "into", "onto", "on", "at", "for"})


# `process`, `processes` and `files` are class names (System Events, Finder) that AppleScript also takes
# as variable names (②Main on #271, compile-checked: `set process to "1Password"` then `tell application
# process to activate`). After `application` they are the class unless the script binds them.
_CLASS_WORDS = frozenset({"process", "processes", "files"})
_IDENT = r"\|[^|\n]*\||[A-Za-z_][A-Za-z0-9_]*"
_BINDING = re.compile(
    r"\bset\s+(" + _IDENT + r")\s+to\b"                          # set x to …
    r"|\bset\s+my\s+(" + _IDENT + r")\s+to\b"                    # set my x to …
    r"|\bset\s+(" + _IDENT + r")\s+of\s+me\s+to\b"                # set x of me to …
    r"|\bset\s+\{([^}\n]*)\}\s+to\b"                              # set {a, b} to …
    r"|\bcopy\b[^\n]*?\bto\s+(" + _IDENT + r"|\{[^}\n]*\})"        # copy … to x / {a, b}
    r"|\bproperty\s+(" + _IDENT + r")\s*:"                       # property x : …
    r"|\b(?:global|local)\s+([^\n]*)"                             # global a, b
    r"|\brepeat\s+with\s+(" + _IDENT + r")\s+(?:in|from)\b"      # repeat with x in / from
    r"|^[ \t]*(?:on|to)\s+(?:" + _IDENT + r")\b([^\n]*)",          # a handler's line: its parameters
    re.I | re.M)
_PROCESS_WORD = re.compile(r"\bprocess(?:es)?\b", re.I)


def _bound_names(code: str) -> set[str]:
    """The names a script binds as variables (set, copy … to, property, global/local, repeat with, a
    handler's parameters), lower case, without pipes."""
    names: set[str] = set()
    for m in _BINDING.finditer(code):
        for group in m.groups():
            for part in re.findall(_IDENT, group or ""):
                names.add(part.strip("|").lower())
    return names


def _talks_to_system_events(script: str) -> bool:
    return any(_system_events(app) for app in script_apps(script))


def _talks_to_finder(script: str) -> bool:
    return any(app_key(app) == "finder" or app.strip().lower() == "com.apple.finder"
               or any(b.lower() == "com.apple.finder" for b in _bundles_of(app)) for app in script_apps(script))


def _class_after_application(name: str, script: str, bound: set[str]) -> bool:
    """Whether `application <name>` is the class (②Main's gate on #271): `process` / `processes` only in a
    script that names System Events by a literal, `file` / `files` only in one that names Finder, and
    never a word the script binds. Anywhere else the word is a value, so the target is computed."""
    if name in bound:
        return False
    if name in ("process", "processes"):
        return _talks_to_system_events(script)
    if name in ("file", "files"):
        return _talks_to_finder(script)
    return True


def _computed_process(code: str, script: str) -> str | None:
    """In a System Events script, a process named other than by a literal string or a filter: `tell
    process x`, `process 1`, `process (…)` (②Main on #271). A filter (`first process whose frontmost is
    true`) is a query, not a name: it stays asked every time with the whole script shown."""
    for m in _PROCESS_WORD.finditer(code):
        at = _GAP.match(code, m.end()).end()
        following = code[at:at + 1]
        if not following or following == '"' or following in "),}]\r\n":
            continue
        word = _WORD.match(code, at)
        if word is not None and word.group(0).lower() in _NOT_A_TARGET:
            continue
        if word is not None and word.group(0).lower() == "named" and \
                code[_GAP.match(code, word.end()).end():][:1] == '"':
            continue                                     # `process named "Notes"`: a literal name
        line_end = script.find("\n", m.start())
        return script[m.start():line_end if line_end != -1 else len(script)].strip()[:80]
    return None


def computed_app_target(script: str) -> str | None:
    """Where a script names the app it talks to other than as a literal string — `tell application
    ("1Pass" & "word")`, `tell application x`, `application id x`, a raw `«class capp»` — or None
    (v0.1.63 H4, ⓪Plan's rule). An app chosen while the script runs can't be checked against the
    never-list, so mac_applescript refuses the script instead of asking. `application` as a class name
    is no target (`current application's …`, `tell current application to`, `every application process`
    all go on with a word or mark skipped below); comments and strings are not read. A literal in
    parentheses (`application ("Notes")`) counts as computed: refused, and the message names the form."""
    code = _mask(script)
    if raw := _RAW_APP_CLASS.search(code):
        return script[raw.start():raw.end()]
    bound = _bound_names(code) & _CLASS_WORDS
    for m in _APP_WORD.finditer(code):
        at = _GAP.match(code, m.end()).end()
        following = code[at:at + 1]
        if not following or following == '"' or following in "\r\n":
            continue
        word = _WORD.match(code, at)
        if word is None and following not in "(«":
            continue                                      # ")", ",", a line's end: the class itself
        if word is not None:
            name = word.group(0).lower()
            if name == "id" and code[_GAP.match(code, word.end()).end():][:1] == '"':
                continue
            if name in _NOT_A_TARGET and _class_after_application(name, script, bound):
                continue
        line_end = script.find("\n", m.start())
        return script[m.start():line_end if line_end != -1 else len(script)].strip()[:80]
    if _talks_to_system_events(script):
        return _computed_process(code, script)
    return None


def script_apps(script: str) -> list[str]:
    """The apps an AppleScript names, in order, without repeats (0.1.61 §A2's "apps" category and
    mac_applescript check these against the never-list). Repeats are by exact spelling, never by
    `app_key`: "Notes" and ".../Notes.app" are two names to check, because the second can be a renamed
    bundle that is really 1Password (②Main on #271: folding them by key let the path go unchecked)."""
    script = script or ""
    code = _mask(script)
    seen: list[str] = []
    for m in _SCRIPT_APP.finditer(code):
        end = code.find('"', m.end())           # the literal's closing quote (its inside is blanked)
        name = script[m.end():end] if end != -1 else ""
        if name and name not in seen:
            seen.append(name)
    return seen


# System Events reaches any app through its process: `tell process "1Password"`, `application process
# "1Password"`, `first process whose bundle identifier is "com.1password.1password"`.
_SYSTEM_EVENTS = frozenset({"system events", "com.apple.systemevents"})


def _string_literals(script: str) -> list[str]:
    """Every string literal in the script, outside comments (`_mask` keeps only their quotes)."""
    code = _mask(script)
    quotes = [i for i, c in enumerate(code) if c == '"']
    return [script[a + 1:b] for a, b in zip(quotes[::2], quotes[1::2])]


def _system_events(app: str) -> bool:
    return (app_key(app) in _SYSTEM_EVENTS or app.strip().lower() in _SYSTEM_EVENTS
            or any(b.lower() == "com.apple.systemevents" for b in _bundles_of(app)))


def never_listed_target(script: str) -> str | None:
    """The first app on the never-list the script reaches, or None. An app it names; and, when it talks to
    System Events or another high-reach app (Finder `open application file id "…"`, a path to the bundle),
    any string in it that names a never-list app — a process by its name or bundle id is that app (v0.1.63
    H4, ③Hands' process-name point and ②Main's review, written by ⓪Plan on Opus 5.5 at the user's request).
    Text a shell or another script runs (`do shell script "open -a …"`, `run script "…"`) is not read here;
    such a script is app_risky, asked every time with the whole script shown.
    Partial matches (`whose name contains "1Pass"`) are not refused here; such a script is still asked
    every time with the whole script shown, because System Events is high-reach."""
    apps = script_apps(script)
    for app in apps:
        if never_touched(app):
            return app
    if any(_system_events(app) or _high_reach(app) for app in apps):
        for text in _string_literals(script):
            if text.strip() and text not in apps and never_touched(text):
                return text
    return None


def sends_on_return(bundle_id: str, name: str) -> bool:
    return _matches(policy()["sends_on_return"], bundle_id, name)


def built_in_lists() -> dict:
    """What Settings shows: the never-list and the two limited tiers, by label."""
    p = policy()
    return {"never": [g["label"] for g in p["denied"]],
            "look_only": [g["label"] for g in p["look_only"]],
            "click_only": [g["label"] for g in p["click_only"]]}


# ── when to ask ──────────────────────────────────────────────────────────────

# 0.1.61 §A11: money moves (`money`: a card every time, in every mode) and the other risky steps
# (`app_risky`: delete, send, submit… — a card every time, never remembered) are told apart.
_MONEY_WORDS = re.compile(
    r"\b(pay|purchase|buy|order|checkout|check out|transfer|pagar|comprar|transferir|bezahlen|kaufen|"
    r"überweisen|payer|acheter|virement)\b|付款|支付|购买|下单|转账|汇款|確認購入|支払|購入|振込",
    re.I)
# `attendee(s)` (v0.1.63, the user 2026-10-20; written by ⓪Plan on Opus 5.5): adding an attendee to an
# iCloud or Exchange calendar event sends an invitation email, which is sending on the user's behalf.
_RISKY_WORDS = re.compile(
    r"\b(delete|remove|erase|trash|discard|send|submit|sign|post|publish|confirm|attendee|attendees|eliminar|borrar|enviar|"
    r"löschen|entfernen|senden|absenden|supprimer|effacer|envoyer|soumettre|publier)\b"
    r"|删除|移除|清空|发送|提交|发布|削除|送信|提出|投稿",
    re.I)
_RISKY_KEYS = {"cmd+delete", "cmd+backspace", "cmd+shift+delete", "cmd+shift+backspace", "cmd+shift+d",
               "cmd+return", "cmd+enter", "cmd+option+delete", "cmd+alt+delete"}


def risky_label(label: str | None) -> bool:
    """A button or menu item whose real label (read from the app, not the model's
    words) deletes, sends, pays, buys, transfers or submits."""
    return money_label(label) or (bool(label) and bool(_RISKY_WORDS.search(str(label))))


def money_label(label: str | None) -> bool:
    """A label that moves money: pay, buy, purchase, order, check out, transfer (0.1.61 §A11).
    Such a step is `money`: a card every time, in every mode, Full access included."""
    return bool(label) and bool(_MONEY_WORDS.search(str(label)))


# Apps that reach every other app or the whole Mac (0.1.61 §A4): their card never offers
# "Always". System Settings is on the never-list besides. Shortcuts and its scripting target run any
# Shortcut the user has, which can run a shell script — the same reach as Terminal (②Main, #267).
HIGH_REACH = frozenset({"com.apple.systemevents", "com.apple.Terminal", "com.googlecode.iterm2",
                        "com.apple.finder", "com.apple.systempreferences", "com.apple.ScriptEditor2",
                        "com.apple.shortcuts", "com.apple.shortcuts.events"})


def always_label(bundle_id: str, name: str) -> str:
    """What an app card's "Always" stores ("" hides "Always": a high-reach app)."""
    return "" if bundle_id in HIGH_REACH else (name or bundle_id)


# What a script can do past the app it names: run a shell outside the sandbox (`do shell script`,
# Terminal's `do script`, iTerm's `write text`), run other script text, run JavaScript in a page
# with the user's logins, type or click into whatever is in front (`keystroke`, `key code`), or move
# files. The island answers an `app` card by its kind alone (0.1.61), not by reading the script as
# approvals._RISKY_SCRIPT did, so this covers at least every word that rule caught (delete, send,
# move, do shell script, purchase, buy, pay, submit, transfer, empty trash).
_SCRIPT_REACH = re.compile(
    r"\b(?:do\s+shell\s+script|do\s+script|run\s+script|load\s+script|store\s+script|do\s+javascript|"
    r"execute\s+javascript|write\s+text|keystroke|key\s+code|move|empty\s+trash)\b", re.I)
# The same steps without those words (0.1.63, found reviewing D4): a raw Apple event in chevrons
# («event sysoexec» is `do shell script`), AppleScriptObjC (`use framework`, `current application's
# NSTask`), and Standard Additions writing a file from the script itself (`open for access`, `write`,
# `set eof`).
# Reading the user's files and carrying them off (0.1.63, user 2026-10-20): Standard Additions `read`
# (read any file), `open location` and a `URL` (hand a URL — which can carry a secret — to the browser
# or another app, outside the "offline after reading a page" rule), and the `clipboard` (read it or
# stuff it). Without these a plain "app" script could read `~/.aws` and send it out through Safari's
# `open location`, unwrapped. A plain word such as a note named "read me" or "url list" also matches:
# that only asks more.
# Saving and exporting (v0.1.63, the user 2026-10-20; written by ⓪Plan on Opus 5.5): Apple's standard suite
# gives nearly every scriptable app `save … in <file>` and `close … saving in <file>`, and Pages, Numbers,
# Keynote, Music and Photos also `export … to <file>` (checked with sdef). A script that saves or exports
# writes a file the user never sees, wherever it says — `~/Library/LaunchAgents` too.
_SCRIPT_REACH_OTHERWISE = re.compile(
    r"«|\b(?:current\s+application|use\s+framework|open\s+for\s+access|open\s+location|read|write|"
    r"set\s+eof|clipboard|URL|save|saving|export|exporting)\b", re.I)
# A script for one of these is a script for every app (System Events drives any process, and is
# how a script reaches an app the never-list names without naming it), the shell, or the files.
_HIGH_REACH_NAMES = frozenset({"system events", "terminal", "iterm", "iterm2", "finder", "system settings",
                               "system preferences", "script editor", "shortcuts", "shortcuts events"})


def _high_reach(app: str) -> bool:
    """By `app_key` (so "System Events.app" and its full path are System Events, v0.1.63 H4), by a
    bundle id the script gives, or by the bundle id really behind the name or path (a renamed copy of
    Terminal is still Terminal)."""
    reach_ids = {b.lower() for b in HIGH_REACH}
    key = app_key(app)
    if key in _HIGH_REACH_NAMES or key in reach_ids or app.strip().lower() in reach_ids:
        return True
    return any(b.lower() in reach_ids for b in _bundles_of(app))


def script_kind(script: str) -> tuple[str, list[str]]:
    """How an AppleScript is asked (0.1.61 §A11; `mac_applescript`, and run_command's osascript in
    the "apps" category): (kind, the apps it names).
    - money words → `money` (every time, every mode);
    - delete / send / submit… words, a step past the app it names (a shell, other script text,
      JavaScript, keystrokes, moving files; also raw «events», AppleScriptObjC and Standard
      Additions' file writes), or a high-reach app (System Events, Terminal, iTerm,
      Finder, System Settings, Script Editor) → `app_risky` (every time, shown in full; the island
      does not answer it);
    - otherwise, a script that names apps → `app` (once per app, like Hands);
    - one that names no app → `opaque` (every time).
    The never-list is checked before any of this (`never_touched` on each named app)."""
    apps = script_apps(script)
    if money_label(script):
        return "money", apps
    if (_RISKY_WORDS.search(script) or _SCRIPT_REACH.search(script) or _SCRIPT_REACH_OTHERWISE.search(script)
            or any(_high_reach(a) for a in apps)):
        return "app_risky", apps
    return ("app" if apps else "opaque"), apps


def risky_keys(keys: str, *, bundle_id: str, app: str) -> bool:
    keys = keys.strip().lower()
    if keys in _RISKY_KEYS:
        return True
    return keys in ("return", "enter") and sends_on_return(bundle_id, app)


def risky_text(text: str, *, bundle_id: str, app: str) -> bool:
    """Typed text ending in a newline sends in messaging and mail apps."""
    return text.endswith("\n") and sends_on_return(bundle_id, app)


def session_for(job_id: str) -> str | None:
    with _lock:
        return _sessions.get(job_id)


def remember_session(job_id: str, session: str) -> None:
    with _lock:
        _sessions[job_id] = session


def forget_job(job_id: str) -> str | None:
    """A job ended: its Stop mark goes; returns its cursor session to end. (Its "for this task"
    grants are the permission store's: `permissions.forget_task`.)"""
    with _lock:
        _stopped.discard(job_id)
        return _sessions.pop(job_id, None)


# ── Stop ─────────────────────────────────────────────────────────────────────

def _work_in_flight() -> set[int]:
    from server.services import desktop_status
    with desktop_status._lock:
        return set(desktop_status._working)


def stop_running_jobs() -> list[str]:
    """Every job and every chat turn (or scheduled run) running now refuses its further Hands calls —
    each checked before its first request and again after every card — and so does a job such a turn
    starts afterwards (`carry_stop_to`). Work started later otherwise does not. H3: all chat turns in
    flight, not only those that used Hands, as with jobs."""
    from server.services import background_jobs
    running = [job_id for job_id, job in background_jobs._jobs.items() if job.phase != "finished"]
    turns = _work_in_flight()
    with _lock:
        _stopped.update(running)
        _stopped.update(_sessions)
        _stopped_turns.intersection_update(turns)
        _stopped_turns.update(turns)
    return running


def carry_stop_to(job_id: str) -> None:
    """A job started by a stopped chat turn is stopped too (②Main's review of #290, point 5): it was
    not running at the Stop, but it is that turn's work continued elsewhere. Called right after the
    job is made, before it can run."""
    if stopped(None):
        with _lock:
            _stopped.add(job_id)


def stopped(job_id: str | None) -> bool:
    """A job by its id; without one (a chat turn), the work this call runs in."""
    if job_id is not None:
        with _lock:
            return job_id in _stopped
    from server.services import desktop_status
    activity = desktop_status._current.get()
    turns = _work_in_flight()
    with _lock:
        _stopped_turns.intersection_update(turns)
        return activity is not None and activity["id"] in _stopped_turns


def permission_prompt_once() -> bool:
    """True the first time in this process: Hands asks macOS to show its prompt once."""
    global _permission_asked
    with _lock:
        first, _permission_asked = not _permission_asked, True
    return first


# ── trace ────────────────────────────────────────────────────────────────────

def _trace_dir() -> Path:
    return _private_dir(_private_dir(_dir()) / "trace")


def prune_trace(today: date | None = None) -> None:
    today = today or date.today()
    folder = _dir() / "trace"
    if not folder.is_dir():
        return
    for path in folder.glob("*.jsonl"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if (today - day).days >= TRACE_DAYS:
            path.unlink(missing_ok=True)


def trace(entry: dict) -> None:
    """Append one Hands call (0600 file, 0700 folder). Never typed text: its length."""
    now = datetime.now(timezone.utc)
    line = json.dumps({"at": now.isoformat(timespec="seconds"), **entry}, ensure_ascii=False)
    path = _trace_dir() / f"{now.date().isoformat()}.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(line + "\n")
    prune_trace(now.date())


def read_trace(days: int = TRACE_DAYS, limit: int = 500) -> list[dict]:
    folder = _dir() / "trace"
    if not folder.is_dir():
        return []
    cutoff = date.today() - timedelta(days=min(max(days, 1), TRACE_DAYS) - 1)
    out: list[dict] = []
    for path in sorted(folder.glob("*.jsonl"), reverse=True):
        try:
            if date.fromisoformat(path.stem) < cutoff:
                continue
            lines = path.read_text().splitlines()
        except (ValueError, OSError):
            continue
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
            if len(out) >= limit:
                return out
    return out


def _reset_for_tests() -> None:
    global _permission_asked
    with _lock:
        _sessions.clear()
        _stopped.clear()
        _stopped_turns.clear()
        _permission_asked = False

