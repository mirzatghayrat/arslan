"""HOOK-1 (docs/plans/0164/HOOK-plugin-hooks.md): a plugin's hooks read, stored and shown on its card. Nothing runs.

On top of CAP8-2's hook rule (#825): the five supported events (PreToolUse, PostToolUse, SessionStart,
UserPromptSubmit, Stop) with `type: "command"` are stored, ready for HOOK-2 and HOOK-3, never run here. Another type on
a supported event refuses the plugin, unless that event is also on the non-blocking list (then it is stored as "won't
run"). Claude Code's tool names map to Arslan's by a fixed table, and a matcher that maps to nothing is stored as
"matches nothing in Arslan, never runs". A hook's timeout is at most 10 s. Each hook has its own switch. An update
that changes any hook switches the plugin off until its card. Hook format: https://code.claude.com/docs/en/hooks

On a scratch HOME and data folder, with fake Claude Code folders, as CAP8-2's tests.
"""
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from server.db.models import CapabilitySource, SkillPack
from server.services import agent_skills, plugin_hooks, plugin_package, skill_import, terminal_exec
from tests.server.test_cap8_2_import_skills_plugins import (PLUGIN_FILES, _all, _plugin, _row, _scan, _skill, _tick,
                                                            api, home, offline)
from tests.server.test_cap8_2_plugin_hooks import CONNECTION, _files_under, _install, _post, _update, spawns

pytestmark = pytest.mark.asyncio
__all__ = ["api", "home", "offline", "spawns"]           # fixtures, used by name

SUPPORTED = ["PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "Stop"]


def _map(**events) -> str:
    """A hooks.json: each event's groups as (matcher, handler...) tuples."""
    return json.dumps({"hooks": {event: [{**({"matcher": m} if m is not None else {}), "hooks": list(handlers)}
                                         for m, *handlers in groups] for event, groups in events.items()}})


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


# ── the user's three ────────────────────────────────────────────────────────────────────────────────────────────

async def test_a_blocking_type_hook_is_refused_and_leaves_no_files(api, home, offline, tmp_path):
    _plugin(home, {**PLUGIN_FILES, **CONNECTION,
                   "hooks/hooks.json": _map(PreToolUse=[("Bash", _cmd("echo ok"))],
                                            PermissionRequest=[("Bash", _cmd("echo ok"))])})
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["refused"] == "hooks" and row["refused_part"] == "PermissionRequest" and row["tick"] is False
    before = _files_under(tmp_path / "data")
    assert (await _post(api, plugins=[_tick(row)]))[row["id"]]["state"] == "refused"
    assert offline == [] and not (home / ".agents").exists()
    assert _files_under(tmp_path / "data") == before
    assert await _all(CapabilitySource) == [] and await _all(SkillPack) == []


@pytest.mark.parametrize("event", ["FutureEvent", "pretooluse", "Stop ", "TaskCreated"])
async def test_an_unknown_event_is_refused(api, home, event):
    _plugin(home, {**PLUGIN_FILES, "hooks/hooks.json": _map(PreToolUse=[("Bash", _cmd("x"))],
                                                            **{event: [("*", _cmd("x"))]})})
    row = _row(await _scan(api), "plugins", "release-kit")
    # Refused for that event, not the supported PreToolUse beside it.
    assert row["refused"] == "hooks" and row["refused_part"].strip() == event.strip() and row["tick"] is False
    assert (await _post(api, plugins=[_tick(row)]))[row["id"]]["state"] == "refused"
    assert await _all(CapabilitySource) == []


async def test_supported_and_allowed_hooks_are_stored_and_never_registered_or_run(api, home, offline, tmp_path,
                                                                                 every_spawn, monkeypatch):
    ran = tmp_path / "the-hook-ran"
    command = f"touch {ran}"
    files = {**PLUGIN_FILES, **CONNECTION, "hooks/hooks.json": _map(
        PreToolUse=[("Bash", _cmd(command, timeout=5))], PostToolUse=[("Edit|Write", _cmd(command))],
        SessionStart=[("startup", _cmd(command))], UserPromptSubmit=[(None, _cmd(command))],
        Stop=[(None, _cmd(command))], Notification=[("", _cmd(command))]),
        "hooks/guard.sh": f"#!/bin/sh\n{command}\n"}
    card = await _install(api, home, files)
    plugin = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    stored = plugin.candidate["hook_rows"]
    assert [(h["event"], h["kind"], h["on"]) for h in stored] == [
        *((event, "supported", True) for event in SUPPORTED), ("Notification", "wont_run", False)]
    assert all(h["command"] == command for h in stored)
    assert stored[0]["matcher"] == "Bash" and stored[0]["arslan"] == ["run_command"] and stored[0]["timeout"] == 5
    assert stored[1]["arslan"] == ["edit_file", "write_file"]
    # Stored with the plugin, ready to run: the card's rows say what each does.
    shown = card["card"]["hook_rows"]
    assert [h["command"] for h in shown] == [command] * 6
    assert shown[0]["note"] == "Runs with no network and can't change your files."
    assert shown[-1]["note"] == "Arslan doesn't run this hook, so what depends on it may not work."
    assert shown[0]["when"] and shown[0]["matches"] == ["run_command"]
    # Through the rest of Arslan's life: a sync, a page load, a turn with a tool call.
    await agent_skills.sync()
    assert (await api.get("/api/v1/capabilities")).status_code == 200
    await _a_turn_with_a_tool_call(monkeypatch, tmp_path)
    assert not ran.exists() and not [call for call in every_spawn if str(ran) in call]
    # Never registered: no hook file reaches ~/.agents, and nothing there holds the command.
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


# ── the type rule ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["http", "prompt", "agent", "mcp_tool"])
@pytest.mark.parametrize("event", ["PreToolUse", "UserPromptSubmit", "Stop"])
def test_another_type_on_a_supported_event_refuses_the_plugin(kind, event):
    refused = _refused(_map(**{event: [("*", {"type": kind, "url": "https://x.example", "prompt": "p"})]}))
    assert refused.code == "hooks" and event in refused.part and kind in refused.part


@pytest.mark.parametrize("kind", ["http", "prompt", "agent", "mcp_tool"])
@pytest.mark.parametrize("event", ["PostToolUse", "SessionStart"])
def test_another_type_on_an_event_also_on_the_quiet_list_is_stored_as_wont_run(kind, event):
    (row,) = _rows(_map(**{event: [("*", {"type": kind, "url": "https://x.example"})]}))
    assert (row["event"], row["kind"], row["on"]) == (event, "wont_run", False)


@pytest.mark.parametrize("handler", [{"type": "command"}, {"type": "command", "command": ""}, {"command": "x"},
                                     {"type": "shell", "command": "x"}, "echo hi", {"type": ["command"]},
                                     {"type": "command", "command": "x", "if": ["Bash"]},
                                     {"type": "command", "command": "x", "args": "a"},
                                     {"type": "command", "command": "x", "timeout": "5"},
                                     {"type": "command", "command": "x", "timeout": 0},
                                     {"type": "command", "command": "x", "timeout": True}])
def test_a_supported_hook_claude_code_wouldnt_load_refuses_the_plugin(handler):
    assert _refused(_map(PreToolUse=[("Bash", handler)])).code == "unreadable"


def test_a_frontmatter_hook_yaml_cant_hash_is_refused_not_a_crash():
    raw = ("---\nname: notes\ndescription: Notes.\nhooks:\n  PostToolUse:\n    - hooks:\n        - type: command\n"
           "          command: x\n          1: one\n---\n\nBody.\n")
    with pytest.raises(skill_import.HookRefused):
        skill_import.frontmatter_hook_rows(raw)


def test_a_skills_frontmatter_hooks_go_by_the_same_rule():
    raw = ("---\nname: notes\ndescription: Notes.\nhooks:\n  PreToolUse:\n    - matcher: Write\n      hooks:\n"
           "        - type: command\n          command: ./check.sh\n---\n\nBody.\n")
    (row,) = skill_import.frontmatter_hook_rows(raw)
    assert (row["event"], row["arslan"], row["command"], row["kind"]) == ("PreToolUse", ["write_file"], "./check.sh",
                                                                          "supported")
    assert skill_import.frontmatter_hooks(raw) == ["PreToolUse"]
    with pytest.raises(skill_import.HookRefused):
        skill_import.frontmatter_hook_rows(raw.replace("type: command", "type: http"))


# ── the tool-name map ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("matcher", "arslan"), [
    ("Bash", ["run_command"]), ("Write", ["write_file"]), ("Edit", ["edit_file"]), ("Read", ["read_file"]),
    ("Edit|Write", ["edit_file", "write_file"]), ("Read, Bash", ["read_file", "run_command"]),
    (None, ["*"]), ("", ["*"]), ("*", ["*"]), ("Edit.*", ["edit_file"]), ("^(Bash|Read)$", ["run_command", "read_file"]),
    ("Bash|Glob", ["run_command"]),
    ("mcp__tools__read", ["mcp:tools:read"]), ("mcp__plugin_release-kit_tools__read", ["mcp:tools:read"]),
    ("mcp__tools__.*", ["mcp:tools:*"]),
])
def test_claude_codes_tool_names_map_to_arslans(matcher, arslan):
    (row,) = _rows(_map(PreToolUse=[(matcher, _cmd("x"))]), CONNECTION)
    assert row["arslan"] == arslan and row["kind"] == "supported" and row["on"] is True
    assert row["matcher"] == matcher


def test_the_table_names_arslans_real_tools():
    from server.registry import executors
    from server.registry.file_tools import EditFileExecutor, ReadFileExecutor, WriteFileExecutor
    assert plugin_hooks.TOOL_MAP == {"Bash": "run_command", "Write": "write_file", "Edit": "edit_file",
                                     "Read": "read_file"}
    keys = {ReadFileExecutor.key, WriteFileExecutor.key, EditFileExecutor.key, executors.RunCommandExecutor.key}
    assert set(plugin_hooks.TOOL_MAP.values()) == keys


@pytest.mark.parametrize(("event", "matcher"), [
    ("PreToolUse", "Glob"), ("PreToolUse", "WebFetch|Grep"), ("PostToolUse", "mcp__memory__create"),
    ("PostToolUse", "mcp__memory__.*"), ("PreToolUse", "NotebookEdit"), ("PreToolUse", "^Task$"),
    ("PreToolUse", "(unclosed"), ("SessionStart", "resume"), ("SessionStart", "clear|compact"),
])
def test_a_matcher_that_maps_to_nothing_is_stored_as_matching_nothing(event, matcher):
    (row,) = _rows(_map(**{event: [(matcher, _cmd("x"))]}), CONNECTION)
    assert row["arslan"] == [] and row["kind"] == "matches_nothing" and row["on"] is False
    shown = plugin_hooks.card_rows([row])[0]
    assert shown["note"] == "Matches nothing in Arslan, never runs."


@pytest.mark.parametrize("event", ["UserPromptSubmit", "Stop"])
def test_a_matcher_on_an_event_without_one_is_ignored_as_claude_code_does(event):
    (row,) = _rows(_map(**{event: [("Glob", _cmd("x"))]}))
    assert row["arslan"] == ["*"] and row["kind"] == "supported"


# ── the timeout ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("timeout", "stored"), [(None, 10), (600, 10), (10, 10), (3, 3), (2.5, 2.5), (10.5, 10)])
def test_a_hooks_timeout_is_at_most_10_seconds(timeout, stored):
    handler = _cmd("x", **({"timeout": timeout} if timeout is not None else {}))
    (row,) = _rows(_map(PreToolUse=[("Bash", handler)]))
    assert row["timeout"] == stored


# ── the per-hook switch ───────────────────────────────────────────────────────────────────────────────────────

async def test_each_hook_has_its_own_switch(api, home, offline):
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": _map(
        PreToolUse=[("Bash", _cmd("a"), _cmd("b"))], PostToolUse=[("Glob", _cmd("c"))],
        Notification=[("", _cmd("d"))])})
    plugin = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    url = f"/api/v1/capability-hooks/plugin:{plugin.id}"
    first, second = plugin.candidate["hook_rows"][:2]
    off = await api.put(f"{url}/{second['id']}", json={"on": False})
    assert off.status_code == 200 and off.json()["on"] is False
    stored = next(r for r in await _all(CapabilitySource) if r.kind == "plugin").candidate["hook_rows"]
    assert [h["on"] for h in stored] == [True, False, False, False]
    assert (await api.put(f"{url}/{second['id']}", json={"on": True})).status_code == 200
    stored = next(r for r in await _all(CapabilitySource) if r.kind == "plugin").candidate["hook_rows"]
    assert [h["on"] for h in stored] == [True, True, False, False]
    # One that never runs can't be switched on; one that isn't there is 404.
    for never in stored[2:]:
        assert (await api.put(f"{url}/{never['id']}", json={"on": True})).status_code == 409
    assert (await api.put(f"{url}/99", json={"on": False})).status_code == 404
    assert (await api.put("/api/v1/capability-hooks/plugin:nope/0", json={"on": False})).status_code == 404
    assert first["on"] is True


async def test_a_copied_in_skills_hook_switch_is_kept_with_its_record_not_its_folder(api, home):
    raw = ("---\nname: guard-notes\ndescription: Notes.\nhooks:\n  PreToolUse:\n    - matcher: Bash\n      hooks:\n"
           "        - type: command\n          command: ./check.sh\n---\n\nBody.\n")
    _skill(home, "guard-notes", text=raw)
    row = _row(await _scan(api), "skills", "guard-notes")
    assert row["refused"] is None and row["hooks"] == ["PreToolUse"]
    assert (await _post(api, skills=[_tick(row)]))[row["id"]]["state"] == "added"
    (stored,) = agent_skills.entries()["guard-notes"]["hook_rows"]
    assert (stored["command"], stored["arslan"], stored["on"]) == ("./check.sh", ["run_command"], True)
    assert "check.sh" not in (agent_skills.folder("guard-notes") / "SKILL.md").read_text()
    switched = await api.put(f"/api/v1/capability-hooks/skill:guard-notes/{stored['id']}", json={"on": False})
    assert switched.status_code == 200
    assert agent_skills.entries()["guard-notes"]["hook_rows"][0]["on"] is False
    card = (await api.put("/api/v1/capabilities/skill:guard-notes", json={"on": True})).json()["detail"]["card"]
    assert [(h["command"], h["on"]) for h in card["hook_rows"]] == [("./check.sh", False)]


async def test_another_tools_skill_in_the_shared_folder_keeps_its_hooks_in_its_record(api, home):
    """Read in place (CAP6a): its folder isn't Arslan's, so its hooks and their switches are stored in its record."""
    from tests.server.test_cap8_2_import_skills_plugins import _write
    raw = ("---\nname: theirs\ndescription: Notes.\nhooks:\n  Stop:\n    - hooks:\n        - type: command\n"
           "          command: ./more.sh\n          timeout: 30\n---\n\nBody.\n")
    _write(home / ".agents" / "skills" / "theirs", {"SKILL.md": raw})
    await agent_skills.sync()
    switched = await api.put("/api/v1/capabilities/skill:theirs", json={"on": True})
    card = switched.json()["detail"]["card"]
    (shown,) = card["hook_rows"]
    assert (shown["event"], shown["command"], shown["timeout"], shown["matches"]) == ("Stop", "./more.sh", 10, ["*"])
    assert shown["note"] == "Runs with no network and can't change your files." and shown["when"]
    approved = await api.post("/api/v1/skill-folder/theirs/approve", json={"digest": card["digest"]})
    assert approved.status_code == 200, approved.text
    url = f"/api/v1/capability-hooks/skill:theirs/{shown['id']}"
    assert (await api.put(url, json={"on": False})).status_code == 200
    assert agent_skills.entries()["theirs"]["hook_rows"][0]["on"] is False
    assert (home / ".agents" / "skills" / "theirs" / "SKILL.md").read_text() == raw       # never written on


# ── an update that changes any hook ───────────────────────────────────────────────────────────────────────────

GUARD = _map(PreToolUse=[("Bash", _cmd("./guard.sh"))], SessionStart=[("startup", _cmd("./hello.sh"))])


@pytest.mark.parametrize("changed", [
    _map(PreToolUse=[("Bash", _cmd("./guard.sh --strict"))], SessionStart=[("startup", _cmd("./hello.sh"))]),
    _map(PreToolUse=[("Bash", _cmd("./guard.sh"))], SessionStart=[("startup", _cmd("./hello.sh", timeout=5))]),
    _map(PreToolUse=[("Bash|Edit", _cmd("./guard.sh"))], SessionStart=[("startup", _cmd("./hello.sh"))]),
    _map(PreToolUse=[("Bash", _cmd("./guard.sh"))]),
    _map(PreToolUse=[("Bash", _cmd("./guard.sh"))], SessionStart=[("startup", _cmd("./hello.sh"))],
         SessionEnd=[("", _cmd("./bye.sh"))]),
])
async def test_an_update_changing_any_hook_switches_the_plugin_off_until_its_card(api, home, offline, changed):
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": GUARD})
    old = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    _update(home, "1.1.0", {**PLUGIN_FILES, "hooks/hooks.json": changed}, "1.0.0")
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
                                                               plugin_package.judged_hooks(_snap({**PLUGIN_FILES,
                                                                   "hooks/hooks.json": changed}))]


async def test_an_update_changing_no_hook_leaves_it_on(api, home, offline):
    await _install(api, home, {**PLUGIN_FILES, "hooks/hooks.json": GUARD})
    _update(home, "1.1.0", {**PLUGIN_FILES, "hooks/hooks.json": GUARD,
                            "skills/release-notes/scripts/fmt.py": "print('new')\n"}, "1.0.0")
    row = _row(await _scan(api), "plugins", "release-kit")
    assert row["here"] is True and all(p.enabled for p in await _all(SkillPack))
    plugin = next(r for r in await _all(CapabilitySource) if r.kind == "plugin")
    assert not (plugin.test or {}).get("hooks_added")
