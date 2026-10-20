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


@functools.lru_cache(maxsize=256)
def app_identity(app: str) -> dict | None:
    """{"name", "bundle_id"} for an app name or bundle id, read from the installed app's Info.plist —
    never by launching it (`osascript -e 'id of app "X"'` would). A bundle id is taken as given. None
    when no installed app has that name and it is no bundle id. Running apps outside these folders are resolved by Hands
    (`which_app`) on the Hands path."""
    app = app.strip().removesuffix(".app")
    if not app or "/" in app:
        return None
    for folder in _APP_DIRS:
        plist = Path(folder).expanduser() / f"{app}.app" / "Contents" / "Info.plist"
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


def never_touched(app: str) -> bool:
    """A name or bundle id on the built-in never-list or the user's own — matched by the name and by
    the bundle id of the installed app with that name (0.1.61 §A11), so a script that names an app
    and a rule that holds its bundle id see the same list."""
    app = app.strip()
    identity = app_identity(app) or {}
    bundle = identity.get("bundle_id") or ""
    keys = {app.lower(), bundle.lower()} - {""}
    if any(n.strip().lower() in keys for n in settings()["never"]):
        return True
    return any(_matches(g, bundle or app, app) or _matches(g, app, app) for g in policy()["denied"])


# `tell application "X"`, `tell app "X"`, `application id "com.x"`, `using terms from application "X"`.
_SCRIPT_APP = re.compile(r'\b(?:application|app)\s+(?:id\s+)?"([^"\n]{1,120})"', re.I)


def script_apps(script: str) -> list[str]:
    """The apps an AppleScript names, in order, without repeats (0.1.61 §A2's "apps" category and
    mac_applescript check these against the never-list)."""
    seen: list[str] = []
    for m in _SCRIPT_APP.finditer(script or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


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
_RISKY_WORDS = re.compile(
    r"\b(delete|remove|erase|trash|discard|send|submit|sign|post|publish|confirm|eliminar|borrar|enviar|"
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
# "Always". System Settings is on the never-list besides.
HIGH_REACH = frozenset({"com.apple.systemevents", "com.apple.Terminal", "com.googlecode.iterm2",
                        "com.apple.finder", "com.apple.systempreferences", "com.apple.ScriptEditor2"})


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
_SCRIPT_REACH_OTHERWISE = re.compile(
    r"«|\b(?:current\s+application|use\s+framework|open\s+for\s+access|open\s+location|read|write|"
    r"set\s+eof|clipboard|URL)\b", re.I)
# A script for one of these is a script for every app (System Events drives any process, and is
# how a script reaches an app the never-list names without naming it), the shell, or the files.
_HIGH_REACH_NAMES = frozenset({"system events", "terminal", "iterm", "iterm2", "finder", "system settings",
                               "system preferences", "script editor"})


def _high_reach(app: str) -> bool:
    name = app.strip().lower()
    return name in _HIGH_REACH_NAMES or name in {b.lower() for b in HIGH_REACH}


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

def stop_running_jobs() -> list[str]:
    """Every job running now refuses further Hands calls (jobs started later do not)."""
    from server.services import background_jobs
    running = [job_id for job_id, job in background_jobs._jobs.items() if job.phase != "finished"]
    with _lock:
        _stopped.update(running)
        _stopped.update(_sessions)
    return running


def stopped(job_id: str | None) -> bool:
    with _lock:
        return job_id is not None and job_id in _stopped


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
        _permission_asked = False

