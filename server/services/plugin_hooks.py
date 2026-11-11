"""HOOK-1 (docs/plans/0164/HOOK-plugin-hooks.md): a plugin's hooks, read, stored and shown on its card. Nothing here
runs, registers or copies a hook: HOOK-2 (the runner) and HOOK-3 (the wiring) do that later, from what is stored here.

The user's rule (CAP8-2, `plugin_package.QUIET_HOOK_EVENTS`): a hook is judged by its event's name only, and a guard
never comes in while nothing runs it.
- **The 16 non-blocking events:** stored as `wont_run`, switched off, whatever the handler holds. PostToolUse and
  SessionStart hooks are stored with their full detail (matcher in Claude Code's form and Arslan's, exact command line,
  args, `if`, timeout, the plugin files the command names); one whose matcher maps to no Arslan tool is
  `matches_nothing`. They stay off until HOOK-3 runs them.
- **PreToolUse, UserPromptSubmit and Stop** (`GUARD_EVENTS`): protections, and nothing runs them before HOOK-3. Read
  and stored for the refusal's display (`not_yet`), then the whole plugin is refused (code `hooks`, naming the event),
  leaving nothing. HOOK-3 lifts this refusal once it runs them.
- **Every other event**, or one not recognised (names are matched exactly): refused, as CAP8-2.

A matcher is never run (it would be an unbounded regular expression): it is read by exact tool names and the MCP
shapes only, and anything else is "can't tell", treated as matching every tool. This module has no regex engine.

Claude Code's hook format: https://code.claude.com/docs/en/hooks (matcher rules, handler fields, timeouts).
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import string
from typing import Callable

from server.orchestrator import untrusted

#: Protections nothing runs before HOOK-3: a plugin or skill with one is refused (the user's rule).
GUARD_EVENTS = frozenset({"PreToolUse", "UserPromptSubmit", "Stop"})
#: Claude Code's tool name → Arslan's tool key (server/registry: run_command, file_tools). Fixed: a name not here
#: matches nothing in Arslan. `mcp__<server>__<tool>` maps to that connection's tool (`_mcp`).
TOOL_MAP = {"Bash": "run_command", "Write": "write_file", "Edit": "edit_file", "Read": "read_file"}
MAX_TIMEOUT_S = 10
MAX_MATCHER = 500
#: `supported` is HOOK-3's: no hook is supported (or can be switched on) until something runs it.
SUPPORTED, WONT_RUN, MATCHES_NOTHING, NOT_YET = "supported", "wont_run", "matches_nothing", "not_yet"
NOTES = {WONT_RUN: "Arslan doesn't run this hook, so what depends on it may not work.",
         MATCHES_NOTHING: "Matches nothing in Arslan, never runs.",
         NOT_YET: "Arslan can't run this protection yet, so it isn't there."}
#: What the refusal of a plugin (or a skill) with a protection says (`Refused.note`).
PROTECTIONS = {"plugin": "This plugin's protections can't run in Arslan yet",
               "skill": "This skill's protections can't run in Arslan yet"}
UNSURE = "Can't tell what this matches, so it's treated as matching every tool."
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
#: The docs' rule: only letters, digits, `_`, `-`, spaces, `,` and `|` is an exact name or a list of them.
_EXACT = frozenset(string.ascii_letters + string.digits + "_- ,|")
_NAME = frozenset(string.ascii_letters + string.digits + "_-")
#: SessionStart's matcher is how a session started; Arslan has one: a new conversation.
_STARTS = {"startup": "startup"}
#: The variables a hook's command names a file of its plugin (or its skill's folder) by.
_FOLDER_VARS = ("CLAUDE_PLUGIN_ROOT", "CLAUDE_SKILL_DIR")


def _refused(code: str, part: str, rows: list[dict] | None = None):
    from server.services.plugin_package import Refused
    return Refused(code, part, rows=rows)


def _timeout(value) -> float:
    """Claude Code's `timeout` (seconds), at most MAX_TIMEOUT_S; none, or one that isn't a positive number, means the
    limit. A hook's own can only lower it."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        return MAX_TIMEOUT_S
    return min(value, MAX_TIMEOUT_S)


def _mcp(token: str, connections: dict[str, str]) -> str | None:
    """`mcp__<server>__<tool>` or `mcp__<server>__.*` (Claude Code's plugin form `plugin_<plugin>_<server>` too) for
    one of this plugin's own connections: "mcp:<server>:<tool>" ("*": any of its tools). None: another server's."""
    for alias in sorted(connections, key=len, reverse=True):
        prefix = f"mcp__{alias}__"
        if token.startswith(prefix) and len(token) > len(prefix):
            tool = token[len(prefix):]
            return f"mcp:{connections[alias]}:{'*' if tool == '.*' else tool}"
    return None


def _whole_server(token: str) -> bool:
    """The whole-server form `mcp__<server>__.*`, its server a plain name: the one regex shape that is read."""
    server = token[len("mcp__"):-len("__.*")]
    return token.startswith("mcp__") and token.endswith("__.*") and bool(server) and set(server) <= _NAME


def arslan_matcher(event: str, matcher, connections: dict[str, str]) -> tuple[list[str], bool]:
    """What a hook's matcher matches in Arslan, read and never run: (tool keys, "mcp:<server>:<tool>", "startup", or
    "*" for all; can't tell). Empty: nothing in Arslan. Exact names (split on `|`, and `,` in the docs' plain form),
    and the MCP shapes, are read; anything else (a regular expression, or a matcher that isn't a short string) can't
    be told without running it, so it is treated as matching every tool. UserPromptSubmit and Stop have no matcher
    in Claude Code; one there is ignored."""
    if event in ("UserPromptSubmit", "Stop") or matcher in (None, "", "*"):
        return ["*"], False
    if not isinstance(matcher, str) or len(matcher) > MAX_MATCHER:
        return ["*"], True
    names = TOOL_MAP if event in ("PreToolUse", "PostToolUse") else _STARTS
    tokens = [part.strip() for part in (matcher.replace(",", "|") if set(matcher) <= _EXACT else matcher).split("|")]
    tokens = [token for token in tokens if token]
    if not tokens or not all(set(token) <= _NAME or (names is TOOL_MAP and _whole_server(token)) for token in tokens):
        return ["*"], True
    found = [names.get(token) or (_mcp(token, connections) if names is TOOL_MAP else None) for token in tokens]
    return list(dict.fromkeys(name for name in found if name)), False


def _plain(value):
    """JSON's form of a hook as declared: YAML may key a mapping by a number, which JSON can't sort beside text."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _digest(event: str, matcher, handler, where: str, scripts: dict[str, str]) -> str:
    """The whole hook as declared, every field (read or not), where it is declared, and the plugin files its command
    names: any change to them, or a move, is a change (`changed`)."""
    try:
        return hashlib.sha256(json.dumps([event, _plain(matcher), _plain(handler), where, scripts], sort_keys=True,
                                         default=str).encode()).hexdigest()
    except (TypeError, ValueError, RecursionError) as exc:     # nested past the limit
        raise _refused("unreadable", where) from exc


#: `read(variable, path)`: the plugin's file a hook names as `${variable}/path`, as (its path in the plugin, its
#: bytes), or None.
Reader = Callable[[str, str], "tuple[str, bytes] | None"]


def _scripts(texts: list[str], read: Reader | None) -> dict[str, str]:
    """{path in the plugin: sha256} of each file the command line names through `${CLAUDE_PLUGIN_ROOT}` (or a
    skill's `${CLAUDE_SKILL_DIR}`) that `read` finds. A path leaving its folder is skipped."""
    found: dict[str, str] = {}
    for word in (w for text in texts for w in text.split()) if read else ():
        for var in _FOLDER_VARS:
            for form in (f"${{{var}}}/", f"${var}/"):
                at = word.find(form)
                rel = posixpath.normpath(word[at + len(form):].strip("\"'`;)&|<>")) if at >= 0 else "."
                if rel.startswith(("/", "..")) or rel == ".":
                    continue
                hit = read(var, rel)
                if hit is not None:
                    found[hit[0]] = hashlib.sha256(hit[1]).hexdigest()
    return dict(sorted(found.items()))


def _row(event: str, matcher, handler, where: str, connections: dict[str, str], read) -> dict:
    """One hook as stored. Never refuses on what the handler holds: the event decides (`rows`)."""
    held = handler if isinstance(handler, dict) else {}
    kind_of, command, args, condition = held.get("type"), held.get("command"), held.get("args"), held.get("if")
    args = args if isinstance(args, list) and all(isinstance(a, str) for a in args) else None
    command = command if isinstance(command, str) else None
    scripts = _scripts([command or "", *(args or [])], read)
    row = {"event": event, "matcher": matcher if isinstance(matcher, str) else None,
           "type": kind_of if isinstance(kind_of, str) else None, "command": command, "args": args,
           "if": condition if isinstance(condition, str) else None, "timeout": _timeout(held.get("timeout")),
           "arslan": None, "unsure": False, "scripts": scripts, "kind": WONT_RUN, "on": False, "where": where,
           "digest": _digest(event, matcher, handler, where, scripts)}
    if event in GUARD_EVENTS or event in ("PostToolUse", "SessionStart"):
        row["arslan"], row["unsure"] = arslan_matcher(event, matcher, connections)
    if event in GUARD_EVENTS:
        row["kind"] = NOT_YET
    elif row["arslan"] == []:
        row["kind"] = MATCHES_NOTHING
    return row


def rows(events, where: str, connections: dict[str, str] | None = None, read=None) -> list[dict]:
    """One row per hook in an event map (`{event: [{"matcher": ..., "hooks": [handler, ...]}]}`). Raises Refused:
    "hooks" naming the first event neither quiet nor a protection (an empty one included), at once; or, once the
    whole map is read, naming the first protection (`GUARD_EVENTS`), with every row read (`Refused.rows`, for the
    refusal's display); "unreadable" for a shape Claude Code wouldn't load. `connections`: {name Claude Code calls a
    connection of this plugin: its name}. `read(variable, path)`: a file of the plugin, for `_scripts`. Ids are given
    by `numbered`, once every place a plugin declares hooks is read."""
    from server.services.plugin_package import QUIET_HOOK_EVENTS
    if not isinstance(events, dict):
        raise _refused("unreadable", where)
    out: list[dict] = []
    guard = None
    for event, groups in events.items():
        if not isinstance(groups, list) or not all(isinstance(g, dict) and isinstance(g.get("hooks"), list)
                                                   for g in groups):
            raise _refused("unreadable", where)
        if event not in QUIET_HOOK_EVENTS and event not in GUARD_EVENTS:
            raise _refused("hooks", untrusted.clean_name(str(event), 80))
        guard = guard or (event if event in GUARD_EVENTS else None)      # by its name, with no handler too
        out += [_row(event, g.get("matcher"), handler, where, connections or {}, read)
                for g in groups for handler in g["hooks"]]
    if guard is not None:
        raise _refused("hooks", guard, rows=numbered(out))
    return out


class Gathered:
    """The rows of every place a plugin declares hooks. A protection's refusal is held until all are read, so the
    refusal shows each hook; any other refusal goes at once. `done` raises the first held one, or numbers the rows."""

    def __init__(self) -> None:
        self.found: list[dict] = []
        self.held = None

    def add(self, read: Callable[[], list[dict]]) -> None:
        from server.services.plugin_package import Refused
        try:
            self.found += read()
        except Refused as exc:
            if exc.rows is None:
                raise
            self.found += exc.rows
            self.held = self.held or exc

    def done(self) -> list[dict]:
        found = numbered(self.found)
        if self.held is not None:
            raise _refused(self.held.code, self.held.part, rows=found)
        return found


def numbered(found: list[dict]) -> list[dict]:
    return [{**row, "id": str(n)} for n, row in enumerate(found)]


def events(found: list[dict]) -> list[str]:
    return [row["event"] for row in found]


def changed(stored: dict, now: list[dict]) -> str | None:
    """The event of the first hook an update added, removed, moved or changed in any way, against what a plugin's
    row stored (`candidate`); None when every hook is as its card showed. A row from before HOOK-1 kept only events."""
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
    """`now`, each switch as it was for a hook that is exactly as before (by its digest). Only a supported hook can
    be on, and none is before HOOK-3."""
    was = {row["digest"]: row["on"] for row in before or []}
    return [{**row, "on": was.get(row["digest"], row["on"]) and row["kind"] == SUPPORTED} for row in now]


def card_rows(found: list[dict]) -> list[dict]:
    """The card's rows: when each fires, what it matches (Claude Code's form and Arslan's, and whether that can't be
    told), its exact command line (with a count of what shows nothing in it), its timeout, its switch, and what
    Arslan will do with it."""
    return [{"id": row["id"], "event": row["event"], "when": WHEN.get(row["event"]), "matcher": row["matcher"],
             "matches": row["arslan"] or [], "matches_note": UNSURE if row.get("unsure") else None,
             "command": row["command"], "args": row["args"], "if": row["if"], "timeout": row["timeout"],
             "kind": row["kind"], "on": row["on"], "note": NOTES[row["kind"]],
             "hidden": untrusted.hidden_summary(" ".join([row["command"] or "", *(row["args"] or [])]))}
            for row in found]


async def switch(owner: str, hook_id: str, on: bool) -> bool | None:
    """One hook's switch, stored: on a plugin's row (`plugin:<id>`) or a skill's record in Arslan's data folder
    (`skill:<key>`), never in the skill's folder. None: no such hook. False: it never runs, so it can't go on (none
    can before HOOK-3). Only the user's request reaches this (the route); nothing runs a hook in this version."""
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
