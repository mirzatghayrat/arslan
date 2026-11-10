"""HOOK-1 (docs/plans/0164/HOOK-plugin-hooks.md): a plugin's hooks, read, stored and shown on its card. Nothing here
runs, registers or copies a hook: HOOK-2 (the runner) and HOOK-3 (the wiring) do that later, from what is stored here.

Built on CAP8-2's rule (`plugin_package.QUIET_HOOK_EVENTS`, judged by the event's name):
- **Supported:** PreToolUse, PostToolUse, SessionStart, UserPromptSubmit and Stop with `type: "command"`. Stored with
  its event, matcher (Claude Code's form and Arslan's), exact command line, timeout (at most 10 s), its own switch (on)
  and its kind. A matcher that maps to no Arslan tool is stored as `matches_nothing`, switched off: no one should
  believe a protection is there when it isn't.
- **Another type on a supported event** (`http`, `prompt`, `agent`, `mcp_tool`) refuses the plugin (code `hooks`),
  unless the event is also on the quiet list (PostToolUse, SessionStart): then it is stored as `wont_run`.
- **Every other event** keeps CAP8-2's rule: on the quiet list, stored as `wont_run`; otherwise the plugin is refused.

Claude Code's hook format: https://code.claude.com/docs/en/hooks (matcher rules, handler fields, timeouts).
"""
from __future__ import annotations

import hashlib
import json
import re

from server.orchestrator import untrusted

SUPPORTED_EVENTS = frozenset({"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "Stop"})
TYPES = frozenset({"command", "http", "prompt", "agent", "mcp_tool"})
#: Claude Code's tool name → Arslan's tool key (server/registry: run_command, file_tools). Fixed: a name not here
#: matches nothing in Arslan. `mcp__<server>__<tool>` maps to that connection's tool (`_mcp`).
TOOL_MAP = {"Bash": "run_command", "Write": "write_file", "Edit": "edit_file", "Read": "read_file"}
MAX_TIMEOUT_S = 10
MAX_MATCHER = 500
SUPPORTED, WONT_RUN, MATCHES_NOTHING = "supported", "wont_run", "matches_nothing"
NOTES = {SUPPORTED: "Runs with no network and can't change your files.",
         WONT_RUN: "Arslan doesn't run this hook, so what depends on it may not work.",
         MATCHES_NOTHING: "Matches nothing in Arslan, never runs."}
WHEN = {"PreToolUse": "before a tool runs", "PostToolUse": "after a tool runs",
        "SessionStart": "when a conversation starts", "UserPromptSubmit": "when you send a message",
        "Stop": "when Arslan is about to finish its answer", "Setup": "when Claude Code runs its first setup",
        "PermissionDenied": "after an action is refused", "PostToolUseFailure": "after a tool fails",
        "Notification": "when a notification is sent", "MessageDisplay": "while a reply is shown",
        "SubagentStart": "when a subagent starts", "StopFailure": "when a turn ends on an error",
        "InstructionsLoaded": "when instruction files are loaded", "CwdChanged": "when the work folder changes",
        "DirectoryAdded": "when a folder is added", "FileChanged": "when a watched file changes",
        "PostCompact": "after the conversation is compacted", "PostModelSwitch": "after the model changes",
        "SessionEnd": "when a conversation ends"}
#: The docs' rule: only letters, digits, `_`, `-`, spaces, `,` and `|` is an exact name or a list of them; anything
#: else is an unanchored JavaScript regular expression. "*", "" or no matcher match all.
_EXACT = re.compile(r"[A-Za-z0-9_\- ,|]+")
#: SessionStart's matcher is how a session started; Arslan has one: a new conversation.
_STARTS = {"startup": "startup"}


def _refused(code: str, part: str):
    from server.services.plugin_package import Refused
    return Refused(code, part)


def _timeout(value, where: str) -> float:
    """Claude Code's `timeout` (seconds), at most MAX_TIMEOUT_S; none means the limit. A hook's own can only lower it."""
    if value is None:
        return MAX_TIMEOUT_S
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise _refused("unreadable", where)
    return min(value, MAX_TIMEOUT_S)


def _mcp(name: str, connections: dict[str, str], regex: bool) -> str | None:
    """`mcp__<server>__<tool>` (or, as a regex, `mcp__<server>__.*`) for one of this plugin's own connections, by its
    name or Claude Code's plugin form `plugin_<plugin>_<server>`: "mcp:<server>:<tool>" ("*": any of its tools)."""
    for alias in sorted(connections, key=len, reverse=True):
        prefix = f"mcp__{alias}__"
        if regex and re.fullmatch(rf"\^?{re.escape(prefix)}\.[*+]\$?", name):
            return f"mcp:{connections[alias]}:*"
        if not regex and name.startswith(prefix) and len(name) > len(prefix):
            return f"mcp:{connections[alias]}:{name[len(prefix):]}"
    return None


def arslan_matcher(event: str, matcher, connections: dict[str, str]) -> list[str]:
    """What a supported hook's matcher matches in Arslan: tool keys, "mcp:<server>:<tool>", "startup", or "*" (all).
    Empty: nothing in Arslan. UserPromptSubmit and Stop have no matcher in Claude Code; one there is ignored."""
    if event in ("UserPromptSubmit", "Stop") or matcher in (None, "", "*"):
        return ["*"]
    names = TOOL_MAP if event in ("PreToolUse", "PostToolUse") else _STARTS
    if _EXACT.fullmatch(matcher):
        wanted = [part.strip() for part in re.split(r"[|,]", matcher) if part.strip()]
        found = [names.get(name) or (_mcp(name, connections, False) if names is TOOL_MAP else None) for name in wanted]
    else:
        try:
            pattern = re.compile(matcher)
        except (re.error, RecursionError, OverflowError):
            return []
        found = [arslan for name, arslan in names.items() if pattern.search(name)]
        if names is TOOL_MAP:
            found.append(_mcp(matcher, connections, True))
    return list(dict.fromkeys(name for name in found if name))


def _digest(event: str, matcher, handler, where: str) -> str:
    """The whole hook as declared, every field (read or not): any change to it is a change (`changed`)."""
    try:
        return hashlib.sha256(json.dumps([event, matcher, handler], sort_keys=True, default=str).encode()).hexdigest()
    except (TypeError, ValueError, RecursionError) as exc:     # YAML keys of mixed types, or nested past the limit
        raise _refused("unreadable", where) from exc


def _row(event: str, matcher, handler, where: str, connections: dict[str, str]) -> dict:
    kind_of = handler.get("type") if isinstance(handler, dict) else None
    command = handler.get("command") if isinstance(handler, dict) else None
    row = {"event": event, "matcher": matcher if isinstance(matcher, str) else None, "type": kind_of,
           "command": command if isinstance(command, str) else None, "args": None, "if": None, "arslan": None,
           "timeout": MAX_TIMEOUT_S, "kind": WONT_RUN, "on": False, "where": where,
           "digest": _digest(event, matcher, handler, where)}
    if event not in SUPPORTED_EVENTS:
        return row
    if not isinstance(kind_of, str) or kind_of not in TYPES:
        raise _refused("unreadable", where)
    if kind_of != "command":
        from server.services.plugin_package import QUIET_HOOK_EVENTS
        if event not in QUIET_HOOK_EVENTS:
            raise _refused("hooks", f"{event} ({kind_of})")
        return row
    args, condition = handler.get("args"), handler.get("if")
    if (not isinstance(command, str) or not command.strip()
            or (args is not None and not (isinstance(args, list) and all(isinstance(a, str) for a in args)))
            or (condition is not None and not isinstance(condition, str))
            or (matcher is not None and not (isinstance(matcher, str) and len(matcher) <= MAX_MATCHER))):
        raise _refused("unreadable", where)
    arslan = arslan_matcher(event, matcher, connections)
    row.update(args=args, arslan=arslan, timeout=_timeout(handler.get("timeout"), where), **{"if": condition},
               kind=SUPPORTED if arslan else MATCHES_NOTHING, on=bool(arslan))
    return row


def rows(events, where: str, connections: dict[str, str] | None = None) -> list[dict]:
    """One row per hook in an event map (`{event: [{"matcher": ..., "hooks": [handler, ...]}]}`). Raises Refused:
    "hooks" naming the first event neither supported nor quiet (an empty one included), or a supported event's other
    type; "unreadable" for a shape Claude Code wouldn't load. `connections`: {name Claude Code calls a connection of
    this plugin: its name}. Ids are given by `numbered`, once every place a plugin declares hooks is read."""
    from server.services.plugin_package import QUIET_HOOK_EVENTS
    if not isinstance(events, dict):
        raise _refused("unreadable", where)
    out: list[dict] = []
    for event, groups in events.items():
        if not isinstance(groups, list) or not all(isinstance(g, dict) and isinstance(g.get("hooks"), list)
                                                   for g in groups):
            raise _refused("unreadable", where)
        if event not in QUIET_HOOK_EVENTS and event not in SUPPORTED_EVENTS:
            raise _refused("hooks", untrusted.clean_name(str(event), 80))
        out += [_row(event, g.get("matcher"), handler, where, connections or {}) for g in groups for handler in g["hooks"]]
    return out


def numbered(found: list[dict]) -> list[dict]:
    return [{**row, "id": str(n)} for n, row in enumerate(found)]


def events(found: list[dict]) -> list[str]:
    return [row["event"] for row in found]


def changed(stored: dict, now: list[dict]) -> str | None:
    """The event of the first hook an update added, removed or changed in any way, against what a plugin's row
    stored (`candidate`); None when every hook is as its card showed. A row from before HOOK-1 kept only events."""
    if stored.get("hook_rows") is None:
        before, after = list(stored.get("hooks") or []), events(now)
    else:
        before, after = [r["digest"] for r in stored["hook_rows"]], [r["digest"] for r in now]
    if before == after:
        return None
    at = next((n for n, (a, b) in enumerate(zip(before, after)) if a != b), min(len(before), len(after)))
    longer = now if len(after) > at else stored.get("hook_rows") or [{"event": e} for e in stored.get("hooks") or []]
    return longer[at]["event"] if at < len(longer) else ""


def carry(before: list[dict] | None, now: list[dict]) -> list[dict]:
    """`now`, each switch as it was for a hook that is exactly as before (by its digest)."""
    was = {row["digest"]: row["on"] for row in before or []}
    return [{**row, "on": was.get(row["digest"], row["on"]) and row["kind"] == SUPPORTED} for row in now]


def card_rows(found: list[dict]) -> list[dict]:
    """The card's rows: when each fires, what it matches (Claude Code's form and Arslan's), its exact command line
    (with a count of what shows nothing in it), its timeout, its switch, and what Arslan will do with it."""
    return [{"id": row["id"], "event": row["event"], "when": WHEN.get(row["event"]), "matcher": row["matcher"],
             "matches": row["arslan"] or [], "command": row["command"], "args": row["args"], "if": row["if"],
             "timeout": row["timeout"], "kind": row["kind"], "on": row["on"], "note": NOTES[row["kind"]],
             "hidden": untrusted.hidden_summary(" ".join([row["command"] or "", *(row["args"] or [])]))}
            for row in found]


async def switch(owner: str, hook_id: str, on: bool) -> bool | None:
    """One hook's switch, stored: on a plugin's row (`plugin:<id>`) or a skill's record in Arslan's data folder
    (`skill:<key>`), never in the skill's folder. None: no such hook. False: it never runs, so it can't go on. Only
    the user's request reaches this (the route); nothing runs a hook in this version."""
    from server.db import session as db_session
    from server.db.models import CapabilitySource
    from server.services import agent_skills
    kind, _, ident = owner.partition(":")
    if kind == "plugin":
        async with db_session.AsyncSessionLocal() as db:
            row = await db.get(CapabilitySource, ident)
            if row is None or row.kind != "plugin" or row.state != "installed":
                return None
            found = _switched((row.candidate or {}).get("hook_rows"), hook_id, on)
            if isinstance(found, list):
                row.candidate = {**row.candidate, "hook_rows": found}
                await db.commit()
                return True
            return found
    if kind == "skill":
        async with agent_skills.manifest_lock():
            entry = agent_skills.entries().get(ident)
            found = _switched((entry or {}).get("hook_rows"), hook_id, on)
            if isinstance(found, list):
                agent_skills.record(ident, by=entry["by"], files=entry.get("files"), hook_rows=found)
                return True
            return found
    return None


def _switched(found: list[dict] | None, hook_id: str, on: bool) -> list[dict] | bool | None:
    hit = next((row for row in found or [] if row.get("id") == hook_id), None)
    if hit is None:
        return None
    if on and hit["kind"] != SUPPORTED:
        return False
    return [{**row, "on": on} if row is hit else row for row in found]
