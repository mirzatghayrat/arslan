"""HOOK-1 (docs/plans/0164/HOOK-plugin-hooks.md): a plugin's hooks read, stored and shown on its card. Nothing runs.

The user's rule: a hook is judged by its event's name only, and a guard never installs while nothing runs it.
- On the 16 non-blocking events (CAP8-2's list) a hook comes in as "won't run". PostToolUse and SessionStart command
  hooks are stored with their full detail (the matcher in both forms, command, args, `if`, timeout, the plugin files
  the command names), and stay "won't run" until HOOK-3 runs them.
- PreToolUse, UserPromptSubmit and Stop are protections nothing runs yet: a plugin or skill with one is refused whole,
  leaving no files, as is one with any other event. The protections are still read and shown on the refusal.
- A matcher is never run. It is read by exact tool-name tokens and the MCP shapes; anything else is "can't tell",
  treated as matching every tool. Claude Code's tool names map to Arslan's by a fixed table.
- An update that adds, removes, moves or changes any hook, or a script one names, switches the plugin off until its card.
Hook format: https://code.claude.com/docs/en/hooks

On a scratch HOME and data folder, with fake Claude Code folders, as CAP8-2's tests.
"""
import ast
import copy
import hashlib
import inspect
import json
import re
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from server.db.models import CapabilitySource, SkillPack
from server.services import (agent_skills, capability_flow, plugin_hooks, plugin_package, skill_import, terminal_exec,
                             tool_import)
from tests.server.test_cap7b_plugin_package import PLUGIN as GITHUB_PLUGIN
from tests.server.test_cap7b_plugin_package import _ask, _nothing_stays, _propose, _rows_of, installs, repo
from tests.server.test_cap8_2_import_skills_plugins import (PLUGIN_FILES, _all, _plugin, _row, _scan, _skill, _tick,
                                                            _write, api, home, offline)
from tests.server.test_cap8_2_plugin_hooks import (CONNECTION, SHA, _files_under, _install, _post, _update, github,
                                                   spawns)

pytestmark = pytest.mark.asyncio
__all__ = ["api", "home", "offline", "spawns", "github", "repo", "installs"]           # fixtures, used by name

GUARDS = ["PreToolUse", "UserPromptSubmit", "Stop"]
PROTECTIONS = "This plugin's protections can't run in Arslan yet"
WONT_RUN = "Arslan doesn't run this hook, so what depends on it may not work."
UNSURE = "Can't tell what this matches, so it's treated as matching every tool."


def _map(**events) -> str:
    """A hooks.json: each event's groups as (matcher, handler...) tuples."""
    return json.dumps({"hooks": _events(**events)})


def _events(**events) -> dict:
    return {event: [{**({"matcher": m} if m is not None else {}), "hooks": list(handlers)} for m, *handlers in groups]
            for event, groups in events.items()}


def _cmd(command: str, **more) -> dict:
    return {"type": "command", "command": command, **more}


def _snap(files: dict) -> plugin_package.Snapshot:
    return plugin_package.Snapshot("kit", "0" * 40, {k: v.encode() for k, v in files.items()})


def _rows(hooks_json: str, files: dict | None = None) -> list[dict]:
    return plugin_package.judged_hooks(_snap({**PLUGIN_FILES, **(files or {}), "hooks/hooks.json": hooks_json}))


def _refused(hooks_json: str) -> plugin_package.Refused:
    with pytest.raises(plugin_package.Refused) as refused:
        _rows(hooks_json)
    return refused.value


def _skill_md(name: str, event: str, matcher: str = "Bash", command: str = "./check.sh", more: str = "") -> str:
    return (f"---\nname: {name}\ndescription: Notes.\nhooks:\n  {event}:\n    - matcher: \"{matcher}\"\n      hooks:\n"
            f"        - type: command\n          command: \"{command}\"\n{more}---\n\nBody.\n")


@pytest.fixture
def every_spawn(spawns, monkeypatch):
    """CAP8-2's recorder (os, subprocess.Popen, asyncio's spawners), plus subprocess's helpers and Arslan's own
    command runner, so a hook started by any of them is seen."""
    for name in ("run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"):
        real = getattr(subprocess, name)
        monkeypatch.setattr(subprocess, name, lambda *a, _real=real, _name=name, **k:
                            spawns.append(repr((_name, a, k))) or _real(*a, **k))
    for name in ("run", "_run"):
        real = getattr(terminal_exec, name)

        async def spy(*a, _real=real, _name=name, **k):
            spawns.append(repr((f"terminal_exec.{_name}", a, k)))
            return await _real(*a, **k)
        monkeypatch.setattr(terminal_exec, name, spy)
    return spawns


# ── the user's rule: a protection nothing runs refuses the plugin, and is shown ─────────────────────────────────────

@pytest.mark.parametrize("where", ["hooks.json", "a skill's frontmatter"])
@pytest.mark.parametrize("event", GUARDS)
async def test_a_protection_refuses_the_plugin_whole_and_is_shown_on_the_refusal(api, home, offline, tmp_path,
                                                                                 every_spawn, event, where):
    ran = tmp_path / "the-hook-ran"
    command = f"touch {ran}"
    files = {**PLUGIN_FILES, **CONNECTION}
    if where == "hooks.json":
        files["hooks/hooks.json"] = _map(PostToolUse=[("Edit", _cmd(command))],
                                         **{event: [("Bash", _cmd(command, timeout=5))]})
    else:
        files["skills/release-notes/SKILL.md"] = _skill_md("release-notes", event, command=command)
    _plugin(home, files)
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "hooks" and row["refused_part"] == event and row["tick"] is False
    # Read and shown, so the user sees why: the protection, its command, and that it can't run yet.
    assert row["refused_note"] == PROTECTIONS
    shown = {h["event"]: h for h in row["hook_rows"]}
    assert (shown[event]["command"], shown[event]["kind"], shown[event]["on"]) == (command, "not_yet", False)
    assert shown[event]["note"] == "Arslan can't run this protection yet, so it isn't there."
    before = _files_under(tmp_path / "data")
    result = (await _post(api, plugins=[_tick(row)]))[row["id"]]
    assert result["state"] == "refused" and result["code"] == "hooks"
    assert (await _post(api, plugins=[_tick(row, card="0" * 64)]))[row["id"]]["state"] == "refused"
    assert offline == [] and not (home / ".agents").exists()
    assert _files_under(tmp_path / "data") == before
    assert await _all(CapabilitySource) == [] and await _all(SkillPack) == []
    assert not ran.exists() and not [call for call in every_spawn if str(ran) in call]


@pytest.mark.parametrize("handler", [_cmd("x"), {"type": "http", "url": "https://x.example"}, {"type": "prompt"},
                                     {"type": "agent"}, {"type": "mcp_tool"}, {"type": "shell", "command": "x"},
                                     {"command": "x"}, "echo hi", _cmd("x", timeout="5")])
@pytest.mark.parametrize("event", GUARDS)
def test_a_protection_refuses_by_its_event_alone(event, handler):
    refused = _refused(_map(**{event: [("*", handler)]}))
    assert (refused.code, refused.part) == ("hooks", event)
    assert [r["event"] for r in refused.rows] == [event] and refused.rows[0]["id"] == "0"


@pytest.mark.parametrize("groups", [[], [{"hooks": []}], [{"matcher": "Bash", "hooks": []}]])
@pytest.mark.parametrize("event", GUARDS)
def test_a_protection_with_no_handler_still_refuses_by_its_name(event, groups):
    refused = _refused(json.dumps({"hooks": {"PostToolUse": [{"hooks": [_cmd("x")]}], event: groups}}))
    assert (refused.code, refused.part) == ("hooks", event) and [r["event"] for r in refused.rows] == ["PostToolUse"]
    raw = f"---\nname: notes\ndescription: Notes.\nhooks:\n  {event}: []\n---\n\nBody.\n"
    with pytest.raises(skill_import.HookRefused, match=event):
        skill_import.frontmatter_hook_rows(raw)


def test_every_protection_is_shown_not_only_the_first():
    files = {"skills/release-notes/SKILL.md": _skill_md("release-notes", "Stop", command="./more.sh")}
    with pytest.raises(plugin_package.Refused) as refused:
        _rows(_map(UserPromptSubmit=[(None, _cmd("./prompt.sh"))], SessionStart=[("startup", _cmd("./hi.sh"))]), files)
    assert refused.value.part == "UserPromptSubmit"
    assert [(r["event"], r["command"]) for r in refused.value.rows] == [
        ("UserPromptSubmit", "./prompt.sh"), ("SessionStart", "./hi.sh"), ("Stop", "./more.sh")]


@pytest.mark.parametrize("event", ["FutureEvent", "pretooluse", "Stop ", "TaskCreated", "PermissionRequest"])
async def test_an_unknown_or_other_event_is_refused(api, home, event):
    _plugin(home, {**PLUGIN_FILES, "hooks/hooks.json": _map(PostToolUse=[("Bash", _cmd("x"))],
                                                            **{event: [("*", _cmd("x"))]})})
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "hooks" and row["refused_part"].strip() == event.strip() and row["tick"] is False
    assert (await _post(api, plugins=[_tick(row)]))[row["id"]]["state"] == "refused"
    assert await _all(CapabilitySource) == []


async def test_a_standalone_skills_protection_is_refused_and_shown(api, home):
    _skill(home, "guard-notes", text=_skill_md("guard-notes", "PreToolUse"))
    row = _row(await _scan(api), "skills", "guard-notes")
    assert row["refused"] == "hooks" and row["refused_part"] == "PreToolUse" and row["tick"] is False
    assert row["refused_note"] == "This skill's protections can't run in Arslan yet"
    assert [(h["command"], h["kind"]) for h in row["hook_rows"]] == [("./check.sh", "not_yet")]
    assert (await _post(api, skills=[_tick(row)]))[row["id"]]["state"] == "refused"
    assert await _all(SkillPack) == [] and not (home / ".agents").exists()


# ── the non-blocking events: stored with their detail, "won't run" ─────────────────────────────────────────────────

async def test_quiet_hooks_are_stored_with_their_detail_and_never_registered_or_run(api, home, offline, tmp_path,
                                                                                   every_spawn, monkeypatch):
    ran = tmp_path / "the-hook-ran"
    command = f"touch {ran}"
    files = {**PLUGIN_FILES, **CONNECTION, "hooks/hooks.json": _map(
        PostToolUse=[("Edit|Write", _cmd(command, timeout=5, args=["--fix"], **{"if": "Edit(*.py)"}))],
        SessionStart=[("startup", _cmd(command))], Notification=[("", _cmd(command))]),
        "hooks/guard.sh": f"#!/bin/sh\n{command}\n"}
    card = await _install(api, home, files)
    plugin = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    stored = plugin.candidate["hook_rows"]
    assert [(h["event"], h["kind"], h["on"]) for h in stored] == [
        ("PostToolUse", "wont_run", False), ("SessionStart", "wont_run", False), ("Notification", "wont_run", False)]
    assert all(h["command"] == command for h in stored)
    assert (stored[0]["matcher"], stored[0]["arslan"], stored[0]["timeout"], stored[0]["args"], stored[0]["if"]) == (
        "Edit|Write", ["edit_file", "write_file"], 5, ["--fix"], "Edit(*.py)")
    assert stored[1]["arslan"] == ["startup"]
    shown = card["card"]["hook_rows"]
    assert [h["command"] for h in shown] == [command] * 3 and {h["note"] for h in shown} == {WONT_RUN}
    assert shown[0]["when"] and shown[0]["matches"] == ["edit_file", "write_file"]
    assert "Runs with no network" not in json.dumps(card)          # nothing claims a hook runs
    # Through the rest of Arslan's life: a sync, a page load, a turn with a tool call.
    await agent_skills.sync()
    assert (await api.get("/api/v1/capabilities")).status_code == 200
    await _a_turn_with_a_tool_call(monkeypatch, tmp_path)
    assert not ran.exists() and not [call for call in every_spawn if str(ran) in call]
    agents = _files_under(home / ".agents")
    assert agents and not [path for path, data in agents.items() if str(ran).encode() in data]
    assert not [path for path in agents if Path(path).name in ("hooks.json", "guard.sh")]


async def _a_turn_with_a_tool_call(monkeypatch, tmp_path):
    """One native turn whose model calls read_file once (Bash's and Read's matchers would fire around it in HOOK-3)."""
    from arslan.llm.adapter import LLMAdapter
    from arslan.llm.providers.anthropic_provider import AnthropicProvider
    from server.orchestrator import tool_loop
    from server.registry import executors
    replies = [{"role": "assistant", "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5},
                "content": [{"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "x.md"}}]},
               {"role": "assistant", "stop_reason": "end_turn", "usage": {"input_tokens": 20, "output_tokens": 3},
                "content": [{"type": "text", "text": "Done."}]}]
    sent, called = [], []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=replies[len(sent) - 1])

    class Read:
        async def execute(self, args):
            called.append(args)
            return {"ok": True, "path": "x.md", "content": "notes"}
    adapter = LLMAdapter("anthropic", "claude-opus-5-5")
    adapter._provider = AnthropicProvider("claude-opus-5-5", api_key="k", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setitem(executors.EXECUTORS, "read_file", Read())

    async def resolve():
        return [{"key": "read_file", "description": "Read a file."}]
    result = await tool_loop.run_native(system="S", user_content="Read x.md", history=[], emit=lambda e: None,
                                        on_chunk=lambda c: None, resolve_tools=resolve)
    assert result["final"] == "Done." and called == [{"path": "x.md"}]


@pytest.mark.parametrize("handler", [{"type": "command"}, {"type": "command", "command": ""}, {"command": "x"},
                                     {"type": "shell", "command": "x"}, "echo hi", {"type": ["command"]},
                                     {"type": "http", "url": "https://x.example"}, {"type": "prompt"},
                                     _cmd("x", **{"if": ["Bash"]}), _cmd("x", args="a"), _cmd("x", timeout="5"),
                                     _cmd("x", timeout=0), _cmd("x", timeout=True)])
@pytest.mark.parametrize("event", ["PostToolUse", "SessionStart"])
def test_a_quiet_hook_is_judged_by_its_event_alone(event, handler):
    (row,) = _rows(_map(**{event: [("startup", handler)]}))
    assert row["event"] == event and row["kind"] in ("wont_run", "matches_nothing") and row["on"] is False
    assert row["timeout"] == 10


def test_a_frontmatter_hook_with_a_number_for_a_key_is_stored_not_a_crash():
    raw = ("---\nname: notes\ndescription: Notes.\nhooks:\n  PostToolUse:\n    - hooks:\n        - type: command\n"
           "          command: x\n          1: one\n---\n\nBody.\n")
    (row,) = skill_import.frontmatter_hook_rows(raw)
    assert (row["event"], row["command"], row["kind"]) == ("PostToolUse", "x", "wont_run")


# ── matchers: read, never run ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("matcher", "arslan", "unsure"), [
    ("Bash", ["run_command"], False), ("Write", ["write_file"], False), ("Edit", ["edit_file"], False),
    ("Read", ["read_file"], False), ("Edit|Write", ["edit_file", "write_file"], False),
    ("Read, Bash", ["read_file", "run_command"], False), ("Bash|Glob", ["run_command"], False),
    (None, ["*"], False), ("", ["*"], False), ("*", ["*"], False),
    ("mcp__tools__read", ["mcp:tools:read"], False), ("mcp__plugin_release-kit_tools__read", ["mcp:tools:read"], False),
    ("mcp__tools__.*", ["mcp:tools:*"], False), ("Read|mcp__tools__.*", ["read_file", "mcp:tools:*"], False),
    # Anything else with a regular expression's characters: can't tell, so treated as matching every tool.
    ("Edit.*", ["*"], True), ("^(Bash|Read)$", ["*"], True), ("(?:a?){20000}X", ["*"], True), ("B\\ash", ["*"], True),
    (".*", ["*"], True), ("mcp__.*", ["*"], True), ("^Task$", ["*"], True), ("(unclosed", ["*"], True),
    ("Bash|(Read)", ["*"], True),
])
def test_a_matcher_is_read_by_exact_names_and_never_run(matcher, arslan, unsure):
    (row,) = _rows(_map(PostToolUse=[(matcher, _cmd("x"))]), CONNECTION)
    assert (row["arslan"], row["unsure"], row["matcher"]) == (arslan, unsure, matcher)
    assert row["kind"] == "wont_run" and row["on"] is False
    (shown,) = plugin_hooks.card_rows([row])
    assert shown["matches"] == arslan and shown["matches_note"] == (UNSURE if unsure else None)


@pytest.mark.parametrize("matcher", [["Bash"], 5, "Bash|" * 101])
def test_a_matcher_that_isnt_a_short_string_is_cant_tell(matcher):
    (row,) = _rows(_map(PostToolUse=[(matcher, _cmd("x"))]))
    assert (row["arslan"], row["unsure"]) == (["*"], True)


def test_the_table_names_arslans_real_tools():
    from server.registry import executors
    from server.registry.file_tools import EditFileExecutor, ReadFileExecutor, WriteFileExecutor
    assert plugin_hooks.TOOL_MAP == {"Bash": "run_command", "Write": "write_file", "Edit": "edit_file",
                                     "Read": "read_file"}
    keys = {ReadFileExecutor.key, WriteFileExecutor.key, EditFileExecutor.key, executors.RunCommandExecutor.key}
    assert set(plugin_hooks.TOOL_MAP.values()) == keys


@pytest.mark.parametrize(("event", "matcher"), [
    ("PostToolUse", "Glob"), ("PostToolUse", "WebFetch|Grep"), ("PostToolUse", "mcp__memory__create"),
    ("PostToolUse", "mcp__memory__.*"), ("PostToolUse", "NotebookEdit"), ("SessionStart", "resume"),
    ("SessionStart", "clear|compact"),
])
def test_a_matcher_that_maps_to_nothing_is_stored_as_matching_nothing(event, matcher):
    (row,) = _rows(_map(**{event: [(matcher, _cmd("x"))]}), CONNECTION)
    assert row["arslan"] == [] and row["kind"] == "matches_nothing" and row["on"] is False
    (shown,) = plugin_hooks.card_rows([row])
    assert shown["note"] == "Matches nothing in Arslan, never runs." and shown["matches"] == []


def test_a_pathological_matcher_returns_at_once():
    """Run as a regular expression, each of these takes seconds (growing with the count squared), with the GIL held.
    Counts stay small enough that a regression fails here in seconds rather than hanging the suite."""
    started = time.perf_counter()
    for count in (20000, 30000):
        assert plugin_hooks.arslan_matcher("PostToolUse", f"(?:a?){{{count}}}X", {}) == (["*"], True)
    assert time.perf_counter() - started < 0.05


async def test_a_pathological_matcher_in_another_tools_skill_doesnt_hold_the_start(home):
    _write(home / ".agents" / "skills" / "theirs",
           {"SKILL.md": _skill_md("theirs", "PostToolUse", matcher="(?:a?){30000}X", command="./x.sh")})
    started = time.perf_counter()
    await agent_skills.sync()
    assert time.perf_counter() - started < 2
    assert agent_skills.read_folder("theirs")["hook_rows"][0]["unsure"] is True


def test_no_matcher_is_ever_compiled_or_searched():
    """No regular expression is run on a matcher: the module that reads them has no regex engine at all, and no
    other hook reader hands a matcher to `re`."""
    tree = ast.parse(inspect.getsource(plugin_hooks))
    engines = {"re", "regex", "fnmatch", "sre_compile", "_sre"}
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not imported & engines
    assert not [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in engines]
    call = re.compile(r"\bre\.(compile|search|match|fullmatch|findall|finditer|split|sub)\(")
    for module in (plugin_package, skill_import, tool_import, agent_skills):
        assert not [line for line in inspect.getsource(module).splitlines() if call.search(line) and "matcher" in line]


# ── the timeout ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("timeout", "stored"), [(None, 10), (600, 10), (10, 10), (3, 3), (2.5, 2.5), (10.5, 10),
                                                 ("5", 10), (0, 10), (True, 10)])
def test_a_hooks_timeout_is_at_most_10_seconds(timeout, stored):
    handler = _cmd("x", **({"timeout": timeout} if timeout is not None else {}))
    (row,) = _rows(_map(PostToolUse=[("Bash", handler)]))
    assert row["timeout"] == stored


# ── the per-hook switch ───────────────────────────────────────────────────────────────────────────────────────

async def test_each_hook_has_its_own_switch_and_none_goes_on_before_it_can_run(api, home, offline):
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": _map(
        PostToolUse=[("Bash", _cmd("a"), _cmd("b")), ("Glob", _cmd("c"))], Notification=[("", _cmd("d"))])})
    plugin = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    url = f"/api/v1/capability-hooks/plugin:{plugin.id}"
    stored = plugin.candidate["hook_rows"]
    assert [h["on"] for h in stored] == [False] * 4
    off = await api.put(f"{url}/{stored[1]['id']}", json={"on": False})
    assert off.status_code == 200 and off.json()["on"] is False
    # None runs in this version, so none can be switched on.
    for hook in stored:
        assert (await api.put(f"{url}/{hook['id']}", json={"on": True})).status_code == 409
    stored = next(r for r in await _all(CapabilitySource) if r.kind == "plugin").candidate["hook_rows"]
    assert [h["on"] for h in stored] == [False] * 4
    assert (await api.put(f"{url}/99", json={"on": False})).status_code == 404
    assert (await api.put("/api/v1/capability-hooks/plugin:nope/0", json={"on": False})).status_code == 404


async def test_a_copied_in_skills_hooks_are_kept_with_its_record_not_its_folder(api, home):
    _skill(home, "quiet-notes", text=_skill_md("quiet-notes", "PostToolUse"))
    row = _row(await _scan(api), "skills", "quiet-notes")
    assert row["refused"] is None and row["hooks"] == ["PostToolUse"]
    assert (await _post(api, skills=[_tick(row)]))[row["id"]]["state"] == "added"
    (stored,) = agent_skills.entries()["quiet-notes"]["hook_rows"]
    assert (stored["command"], stored["arslan"], stored["kind"], stored["on"]) == (
        "./check.sh", ["run_command"], "wont_run", False)
    assert "check.sh" not in (agent_skills.folder("quiet-notes") / "SKILL.md").read_text()
    url = f"/api/v1/capability-hooks/skill:quiet-notes/{stored['id']}"
    assert (await api.put(url, json={"on": False})).status_code == 200
    assert (await api.put(url, json={"on": True})).status_code == 409
    card = (await api.put("/api/v1/capabilities/skill:quiet-notes", json={"on": True})).json()["detail"]["card"]
    assert [(h["command"], h["on"], h["note"]) for h in card["hook_rows"]] == [("./check.sh", False, WONT_RUN)]


async def test_another_tools_skill_in_the_shared_folder_keeps_its_hooks_in_its_record(api, home):
    """Read in place (CAP6a): its folder isn't Arslan's, so its hooks and their switches are stored in its record."""
    raw = _skill_md("theirs", "SessionStart", matcher="startup", command="./more.sh", more="          timeout: 30\n")
    _write(home / ".agents" / "skills" / "theirs", {"SKILL.md": raw})
    await agent_skills.sync()
    switched = await api.put("/api/v1/capabilities/skill:theirs", json={"on": True})
    card = switched.json()["detail"]["card"]
    (shown,) = card["hook_rows"]
    assert (shown["event"], shown["command"], shown["timeout"], shown["matches"]) == (
        "SessionStart", "./more.sh", 10, ["startup"])
    assert shown["note"] == WONT_RUN and shown["when"] and shown["on"] is False
    approved = await api.post("/api/v1/skill-folder/theirs/approve", json={"digest": card["digest"]})
    assert approved.status_code == 200, approved.text
    url = f"/api/v1/capability-hooks/skill:theirs/{shown['id']}"
    assert (await api.put(url, json={"on": False})).status_code == 200
    assert (await api.put(url, json={"on": True})).status_code == 409
    assert agent_skills.entries()["theirs"]["hook_rows"][0]["on"] is False
    assert (home / ".agents" / "skills" / "theirs" / "SKILL.md").read_text() == raw       # never written on


# ── every way a skill's frontmatter comes in goes through one reader ─────────────────────────────────────────────

@pytest.fixture
def frontmatter_reads(monkeypatch):
    """Every SKILL.md whose hooks `skill_import.frontmatter_hook_rows` read, by its name in the frontmatter."""
    seen: list[str] = []
    real = skill_import.frontmatter_hook_rows

    def spy(raw, *args, **kwargs):
        seen.append(skill_import.parse_skill_md(raw)["name"])
        return real(raw, *args, **kwargs)
    monkeypatch.setattr(skill_import, "frontmatter_hook_rows", spy)
    return seen


async def test_every_entry_point_reads_a_skills_hooks_through_one_function(api, home, github, frontmatter_reads):
    """The GitHub listing and import (CAP4's card too), the import sheet's skills and plugins, and another tool's
    skill read in place. CAP7b's GitHub plugin: test_a_github_plugins_skill_hooks_*."""
    github["listed/SKILL.md"] = _skill_md("listed", "PostToolUse")
    await skill_import.scan_skills(f"acme/kit@{SHA}")
    await skill_import.prepare_skill(f"acme/kit@{SHA}", "listed/SKILL.md")
    _skill(home, "copied", text=_skill_md("copied", "PostToolUse"))
    _plugin(home, {**PLUGIN_FILES, "skills/release-notes/SKILL.md": _skill_md("release-notes", "PostToolUse")})
    await _scan(api)
    _write(home / ".agents" / "skills" / "theirs", {"SKILL.md": _skill_md("theirs", "PostToolUse")})
    agent_skills.read_folder("theirs")
    assert {"listed", "copied", "release-notes", "theirs"} <= set(frontmatter_reads)
    assert frontmatter_reads.count("listed") == 2


async def test_a_github_plugins_skill_hooks_are_on_its_card_and_its_row(home, repo, installs, execution_db,
                                                                       frontmatter_reads):
    repo["skills/release-notes/SKILL.md"] = _skill_md("release-notes", "PostToolUse", command="./fmt.sh")
    seen: list = []
    result = await _propose(ask=_ask(seen=seen))
    assert result.get("ok") is True, result
    (shown,) = seen[0]["hook_rows"]
    assert (shown["event"], shown["command"], shown["kind"], shown["matches"]) == (
        "PostToolUse", "./fmt.sh", "wont_run", ["run_command"])
    assert seen[0]["hooks"] == ["PostToolUse"]
    plugin = next(r for r in await _rows_of(execution_db, CapabilitySource) if r.kind == "plugin")
    (stored,) = plugin.candidate["hook_rows"]
    assert (stored["command"], stored["where"]) == ("./fmt.sh", "skills/release-notes/SKILL.md")
    assert "release-notes" in frontmatter_reads


@pytest.mark.parametrize("event", GUARDS)
async def test_a_github_plugins_skill_with_a_protection_is_refused(home, repo, installs, execution_db, event):
    repo["skills/release-notes/SKILL.md"] = _skill_md("release-notes", event)
    with pytest.raises(plugin_package.Refused) as refused:
        await plugin_package.prepare(copy.deepcopy(GITHUB_PLUGIN))
    assert event in refused.value.part
    assert [r["command"] for r in refused.value.rows] == ["./check.sh"]
    result = await _propose()
    assert result["ok"] is False
    await _nothing_stays(execution_db)


async def test_capability_flows_skill_card_shows_the_hooks(home, github):
    github["notes/SKILL.md"] = _skill_md("notes", "PostToolUse")
    cand = {"kind": "skill", "repo": "acme/kit", "path": "notes/SKILL.md", "version": SHA, "source": "library"}
    prepared, _ = await capability_flow.prepare_skill(cand)
    assert [(h["command"], h["where"]) for h in prepared["hook_rows"]] == [("./check.sh", "notes/SKILL.md")]


# ── an update that changes any hook ───────────────────────────────────────────────────────────────────────────

QUIET = _map(PostToolUse=[("Bash", _cmd("./guard.sh"))], SessionStart=[("startup", _cmd("./hello.sh"))])
MANIFEST = json.loads(PLUGIN_FILES[".claude-plugin/plugin.json"])


@pytest.mark.parametrize("changed", [
    {"hooks/hooks.json": _map(PostToolUse=[("Bash", _cmd("./guard.sh --strict"))],
                              SessionStart=[("startup", _cmd("./hello.sh"))])},
    {"hooks/hooks.json": _map(PostToolUse=[("Bash", _cmd("./guard.sh"))],
                              SessionStart=[("startup", _cmd("./hello.sh", timeout=5))])},
    {"hooks/hooks.json": _map(PostToolUse=[("Bash|Edit", _cmd("./guard.sh"))],
                              SessionStart=[("startup", _cmd("./hello.sh"))])},
    {"hooks/hooks.json": _map(PostToolUse=[("Bash", _cmd("./guard.sh"))])},
    {"hooks/hooks.json": _map(PostToolUse=[("Bash", _cmd("./guard.sh"))], SessionStart=[("startup", _cmd("./hello.sh"))],
                              SessionEnd=[("", _cmd("./bye.sh"))])},
    # The same hooks in another order, or moved from hooks.json into the manifest.
    {"hooks/hooks.json": _map(SessionStart=[("startup", _cmd("./hello.sh"))], PostToolUse=[("Bash", _cmd("./guard.sh"))])},
    {"hooks/hooks.json": None, ".claude-plugin/plugin.json": json.dumps({**MANIFEST, "hooks": json.loads(QUIET)["hooks"]})},
], ids=["command", "timeout", "matcher", "removed", "added", "reordered", "moved"])
async def test_an_update_changing_any_hook_switches_the_plugin_off_until_its_card(api, home, offline, changed):
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": QUIET})
    old = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    files = {k: v for k, v in {**PLUGIN_FILES, "hooks/hooks.json": QUIET, **changed}.items() if v is not None}
    _update(home, "1.1.0", files, "1.0.0")
    row = _row(await _scan(api), "plugins", "release-kit")
    assert not any(p.enabled for p in await _all(SkillPack))
    assert row["refused"] is None and row["here"] is False                # its card brings it back, as #825's
    listed = next(r for r in (await api.get("/api/v1/capabilities")).json() if r["key"] == f"plugin:{old.id}")
    assert listed["state"] == "setup" and listed["reason"] == "plugin_hooks"
    assert (await api.put(f"/api/v1/capabilities/plugin:{old.id}", json={"on": True})).status_code == 409
    card = (await _post(api, plugins=[_tick(row)]))[row["id"]]
    assert card["state"] == "card"
    done = (await _post(api, plugins=[_tick(row, card=card["card_digest"])]))[row["id"]]
    assert done["state"] == "on", done
    plugins = {r.id: r for r in await _all(CapabilitySource) if r.kind == "plugin"}
    assert plugins[old.id].state == "removed"
    new = next(r for r in plugins.values() if r.id != old.id)
    assert [h["digest"] for h in new.candidate["hook_rows"]] == [h["digest"] for h in
                                                               plugin_package.judged_hooks(_snap(files))]


async def test_an_update_changing_a_script_a_hook_names_switches_it_off(api, home, offline):
    hooks = _map(PostToolUse=[("Bash", _cmd("\"${CLAUDE_PLUGIN_ROOT}/hooks/fmt.sh\" --check"))])
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": hooks, "hooks/fmt.sh": "echo v1\n"})
    old = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    (stored,) = old.candidate["hook_rows"]
    assert stored["scripts"] == {"hooks/fmt.sh": hashlib.sha256(b"echo v1\n").hexdigest()}
    _update(home, "1.1.0", {**PLUGIN_FILES, "hooks/hooks.json": hooks, "hooks/fmt.sh": "echo v2\n"}, "1.0.0")
    await _scan(api)
    listed = next(r for r in (await api.get("/api/v1/capabilities")).json() if r["key"] == f"plugin:{old.id}")
    assert listed["state"] == "setup" and listed["reason"] == "plugin_hooks"


async def test_an_update_changing_no_hook_leaves_it_on(api, home, offline):
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": QUIET})
    _update(home, "1.1.0", {**PLUGIN_FILES, "hooks/hooks.json": QUIET,
                            "skills/release-notes/scripts/fmt.py": "print('new')\n"}, "1.0.0")
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["here"] is True and all(p.enabled for p in await _all(SkillPack))
    plugin = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    assert not (plugin.test or {}).get("hooks_added")
