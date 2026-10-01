"""What Arslan's terminal may run, and when it asks first (0.1.48).

Three answers for any shell command:

  run     just run it. Most commands: reading, listing, converting, building,
          fetching a page, running a script in the user's folder.
  ask     show the user the command first; they may tick "don't ask again" for
          that kind of command (remembered by rule, below). Destructive things
          (recursive delete, force push, overwriting system or credential files,
          `curl | sh`, killing processes, uninstalling) and anything that acts
          OUTWARD for the user: sending mail or messages, posting, uploading,
          controlling other apps (osascript, Shortcuts), installing software.
  forbid  never, even with a tick: wiping disks or the home folder, shutting the
          machine down, fork bombs, reading passwords out of the keychain,
          reading Arslan's own key files.

The destructive and hard-floor detection is Hermes Agent's (MIT, vendored in
arslan/vendor/hermes, used by a large deployed agent and hardened against quoting
and obfuscation tricks). The outward and credential rules are Arslan's own,
because a personal assistant's main risk is acting in the user's name, which a
coding agent's rule set does not cover.

Everything here is a pure function of the command text. It is a guard against
mistakes and against instructions smuggled in through web pages, not a sandbox:
an allowed command runs with the user's own permissions.
"""
from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass

from arslan.vendor.hermes import approval_detection as hermes

ALWAYS_ALLOW_KEY = "terminal_always_allow"
MAX_COMMAND_CHARS = 8000

_POS = hermes._CMDPOS           # command position: start, after ; | && $( ` and sudo/env wrappers

# (rule, pattern, why) — the rule is what "don't ask again" remembers.
_FORBID = [
    ("keychain-secrets", _POS + r"security\s+(?:[^\n]*\s)?(?:find-(?:generic|internet)-password[^\n]*\s-w\b|"
                                r"find-(?:generic|internet)-password[^\n]*\s-g\b|dump-keychain|export\b)",
     "reads passwords out of the keychain"),
    ("arslan-keys", r"(?:\.arslan/secret_key|\.arslan-updater\.key|arslan-signing-backup)",
     "touches Arslan's own key files"),
    # Arslan has no terminal to type an admin password into, and should not act as root:
    # a command that needs sudo is one to hand to the user.
    ("sudo", r"(?:^|[\n;&|`(]|\$\()\s*sudo\b", "needs administrator rights; run it yourself"),
    # macOS roots Hermes' Linux-oriented floor does not name.
    ("macos-roots", _POS + r"rm\s+(?:-[^\s]*\s+)*(?:-[^\s]*[rR][^\s]*\s+)(?:-[^\s]*\s+)*"
                          r"[\"']?/(?:System|Library|Applications|Users|private|Volumes)/?[\"']?(?:\s|$|[;&|)])",
     "recursive delete of a macOS system folder"),
]
_ASK = [
    ("apple-events", _POS + r"osascript\b", "controls other apps (it could send, delete or buy)"),
    ("shortcuts", _POS + r"shortcuts\s+run\b", "runs one of your Shortcuts"),
    ("send-mail", _POS + r"(?:mail|mailx|sendmail|msmtp|mutt|himalaya\s+(?:send|write|reply|forward))\b",
     "sends email"),
    ("send-message", _POS + r"(?:imsg\s+send|xurl\b[^\n]*(?:post|tweet|/2/tweets))",
     "sends a message or posts"),
    ("upload", _POS + r"(?:curl\b[^\n]*(?:\s-(?:[a-zA-Z]*[dFT])\b|\s--(?:data[a-z-]*|form|upload-file|json)\b|"
                      r"-X\s*(?:POST|PUT|PATCH|DELETE)\b|--request\s+(?:POST|PUT|PATCH|DELETE)\b)|"
                      r"wget\b[^\n]*--(?:post|method=(?:POST|PUT|DELETE)))",
     "sends data to a website"),
    ("remote-shell", _POS + r"(?:ssh|scp|sftp|ftp|rsync\b[^\n]*\S+:)\b", "connects to another machine"),
    ("git-push", _POS + r"git\s+(?:[^\n]*\s)?push\b", "publishes to a remote repository"),
    ("publish", _POS + r"(?:npm\s+publish|pnpm\s+publish|yarn\s+publish|twine\s+upload|cargo\s+publish|"
                       r"gh\s+(?:pr|issue|release|repo|gist)\s+(?:create|delete|merge|close|edit|comment)|"
                       r"gh\s+api\b[^\n]*-X\s*(?:POST|PUT|PATCH|DELETE))",
     "publishes or changes something online"),
    ("install", _POS + r"(?:brew\s+(?:install|reinstall|upgrade|tap)|pip3?\s+install|pipx\s+install|"
                       r"npm\s+(?:install|i)\s+(?:-g|--global)|gem\s+install|cargo\s+install)\b",
     "installs software"),
    ("login-items", _POS + r"(?:launchctl\s+(?:load|bootstrap|enable|submit)|defaults\s+write|crontab\b)",
     "changes how your Mac starts or behaves"),
    ("delete", _POS + r"(?:rm|rmdir|unlink|trash|srm)\s", "deletes files"),
]
_FORBID_C = [(k, re.compile(p, re.I), w) for k, p, w in _FORBID]
_ASK_C = [(k, re.compile(p, re.I), w) for k, p, w in _ASK]


@dataclass(frozen=True)
class Assessment:
    level: str              # "run" | "ask" | "forbid"
    rule: str = ""          # what "don't ask again" remembers; "" for run
    reason: str = ""


def as_shell(command: str, argv=None) -> str:
    """One shell string from either form the tool accepts ({command} or legacy {command, argv})."""
    command = str(command or "").strip()
    if not command:
        return ""          # argv alone is not a command; joining would run `'' <argv>`
    if isinstance(argv, list) and argv:
        command = shlex.join([command, *[str(a) for a in argv]])
    return command


def assess(command: str) -> Assessment:
    text = str(command or "")
    if not text.strip():
        return Assessment("forbid", "empty", "no command")
    if len(text) > MAX_COMMAND_CHARS:
        return Assessment("forbid", "too-long", "command is too long to review")
    hard, desc = hermes.detect_hardline_command(text)[:2]
    if hard:
        return Assessment("forbid", "hardline", desc or "can destroy the system")
    normalized = hermes._normalize_command_for_detection(text)
    for key, pattern, why in _FORBID_C:
        if pattern.search(text) or pattern.search(normalized):
            return Assessment("forbid", key, why)
    dangerous, key, desc = hermes.detect_dangerous_command(text)
    if dangerous:
        return Assessment("ask", f"hermes:{key}", desc or "could cause damage")
    for key, pattern, why in _ASK_C:
        if pattern.search(text) or pattern.search(normalized):
            return Assessment("ask", key, why)
    return Assessment("run")


def risk_grade(command: str) -> str:
    """The LOW/MEDIUM/HIGH grade the confirmation layer speaks (run/ask/forbid)."""
    return {"run": "LOW", "ask": "MEDIUM", "forbid": "HIGH"}[assess(command).level]


# ── "don't ask again", remembered by rule ─────────────────────────────────────

async def always_allowed(db) -> set[str]:
    """Rules the user said not to ask about again. Unreadable means none: ask."""
    from server.services import settings_service
    try:
        raw = await settings_service._get_raw(db, ALWAYS_ALLOW_KEY)
        return {str(r) for r in json.loads(raw)} if raw else set()
    except Exception:  # noqa: BLE001 — a standing permission is never inferred from an error
        return set()


async def allow_always(db, rule: str) -> None:
    """Remember a rule. Forbidden rules and the empty rule can never be remembered."""
    from server.services import settings_service
    if not rule or rule in {k for k, _, _ in _FORBID} | {"hardline", "empty", "too-long"}:
        return
    rules = await always_allowed(db) | {rule}
    await settings_service._set_raw(db, ALWAYS_ALLOW_KEY, json.dumps(sorted(rules)))
    await db.commit()


async def forget(db, rule: str) -> None:
    from server.services import settings_service
    rules = await always_allowed(db) - {rule}
    await settings_service._set_raw(db, ALWAYS_ALLOW_KEY, json.dumps(sorted(rules)))
    await db.commit()


def describe(rule: str) -> str:
    """What a remembered rule lets through, in the words the card used when it asked."""
    for key, _, why in _ASK:
        if key == rule:
            return why
    return rule.split(":", 1)[1] if rule.startswith("hermes:") else rule
