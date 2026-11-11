"""The tool table a turn is offered, for every condition that changes it, and the traits of each tool offered.

Each case is a chat turn on a Mac with everything a default install has switched on, or a job, or a scheduled run, with
one condition flipped. For each case this says which tools are listed (`_every_tool`) and which a request is shown
(`_arslan_tools`), as what the case adds to or takes from its base. A tool added, removed or renamed in a case, or an
offer condition changed, shows as a case that lists something else. Each flip must also change the table (its names or
its words), so a condition that stopped mattering shows too. The traits of every tool offered are stated below, with
whether it has its own gate, so a flipped trait shows as the tool it belongs to.
"""
import json
import os
import sys
import types
from pathlib import Path

import pytest

from server.db.models import MCPServer, Tool, Toolset
from server.mcp import supervisor
from server.orchestrator import arslan, tool_loop
from server.registry import hands_tools, tool_defs
from server.services import (
    agent_browser,
    background_jobs,
    permissions,
    personal_context,
    settings_service,
    ssh_nodes,
    task_service,
)
from tests.server.scripted_turn import booted_db_fixture, turn_db_fixture  # noqa: F401 — the fixtures

TASK = types.SimpleNamespace(closed=False)
# A chat turn on a Mac, with everything switched on that a default install has.
CHAT = dict(platform="darwin", task=True, job=False, asker=True, scheduled=False, browser=True, hands=True, skills=True,
            project=False, workspace=True, own_folder=True, default_read=True, lan=False, ssh=False, enrolled=False,
            shell=True, mcp=True)
BASES = {"chat": CHAT, "job": {**CHAT, "job": True}, "scheduled": {**CHAT, "asker": False, "scheduled": True}}
FLIPS = {"platform": "linux", "task": False, "job": True, "asker": False, "scheduled": True, "browser": False,
         "hands": False, "skills": False, "project": True, "workspace": False, "own_folder": False,
         "default_read": False, "lan": True, "ssh": True, "shell": False, "mcp": False}

HANDS = {"desktop_apps", "desktop_access", "desktop_look", "desktop_click", "desktop_type", "desktop_select",
         "desktop_scroll", "desktop_open", "desktop_batch", "desktop_menu", "desktop_press"}
BACKGROUND = {"start_background_work", "background_status", "stop_background_work"}
JOB_ONLY = {"browser_click", "browser_type", "browser_select", "browser_press", "mac_run_shortcut", "mac_applescript",
            "desktop_takeover"}
CHAT_LISTED = {
    "web_search", "web_extract", "render_chart", "recall", "remember", "conversation_search", "memory_note",
    "task_progress", "delegate_work", "update_plan", "ask_user_choice", *BACKGROUND, "browser_open", "browser_look",
    "browser_back", "mac_list_shortcuts", *HANDS, "read_skill", "find_capability", "propose_capability", "create_skill",
    "import_memories", "verify", "whats_new", "my_status", "list_my_capabilities", "read_file", "list_dir",
    "search_files", "write_file", "edit_file", "schedule_task", "list_my_tasks", "cancel_task", "run_command",
    "attach_file", "mcp_1__lookup"}
CHAT_SHOWN = {"web_search", "web_extract", "recall", "remember", "update_plan", "ask_user_choice",
              "start_background_work", *HANDS, "read_skill", "list_my_capabilities", "read_file", "list_dir",
              "search_files", "write_file", "edit_file", "run_command"}
# What a case lists and shows besides its base: (listed +, listed -, shown +, shown -)
NONE = (set(), set(), set(), set())
BASE_CHANGES = {
    "job": (JOB_ONLY, BACKGROUND, {"desktop_takeover"}, {"start_background_work"}),
    "scheduled": (set(), BACKGROUND | {"run_command", "verify"}, set(), {"run_command", "start_background_work"}),
}
FLIP_CHANGES = {
    "chat": {
        "platform": (set(), {"mac_list_shortcuts"}, set(), set()),
        "task": (set(), BACKGROUND | {"delegate_work", "task_progress"}, set(), {"start_background_work"}),
        "job": BASE_CHANGES["job"],
        "asker": BASE_CHANGES["scheduled"],
        "scheduled": NONE,
        "browser": (set(), {"browser_open", "browser_look", "browser_back"}, set(), set()),
        "hands": (set(), HANDS, set(), HANDS),
        "skills": (set(), {"read_skill"}, set(), {"read_skill"}),
        "project": ({"propose_plan_change"}, set(), set(), set()),
        "workspace": (set(), {"write_file", "edit_file", "verify"}, set(), {"write_file", "edit_file"}),
        "own_folder": NONE,
        "default_read": NONE,
        "lan": ({"scan_local_network"}, set(), set(), set()),
        "ssh": ({"ssh_probe", "enroll_node"}, set(), set(), set()),
        "shell": (set(), {"run_command", "verify"}, set(), {"run_command"}),
        "mcp": (set(), {"mcp_1__lookup"}, set(), set()),
    },
    "job": {
        "platform": (set(), {"mac_list_shortcuts", "mac_run_shortcut", "mac_applescript"}, set(), set()),
        "task": (set(), {"delegate_work", "task_progress"}, set(), set()),
        "asker": (set(), {"run_command", "verify"}, set(), {"run_command"}),
        "scheduled": NONE,
        "browser": (set(), {"browser_open", "browser_look", "browser_back", "browser_click", "browser_type",
                            "browser_select", "browser_press"}, set(), set()),
        "hands": (set(), HANDS | {"desktop_takeover"}, set(), HANDS | {"desktop_takeover"}),
    },
    "scheduled": {
        "task": ({"run_command", "verify"}, {"delegate_work", "task_progress"}, {"run_command"}, set()),
        "job": (JOB_ONLY, set(), {"desktop_takeover"}, set()),
        "workspace": (set(), {"write_file", "edit_file"}, set(), {"write_file", "edit_file"}),
        "shell": NONE,
    },
}
# The flips not named for a job or a scheduled run change those as they change a chat turn.
EXTRA = {
    "chat, ssh=True, enrolled=True": ({**CHAT, "ssh": True, "enrolled": True},
                                      ({"ssh_probe", "enroll_node", "ssh_run", "list_nodes"}, set(), set(), set())),
    "chat, no workspace, closed folders": ({**CHAT, "workspace": False, "default_read": False}, (
        set(), {"read_file", "list_dir", "search_files", "write_file", "edit_file", "verify", "attach_file"}, set(),
        {"read_file", "list_dir", "search_files", "write_file", "edit_file"})),
    "job, chosen folder": ({**BASES["job"], "own_folder": False}, NONE),
}


def _apply(listed, shown, changes):
    added, removed, shown_added, shown_removed = changes
    return (listed | added) - removed, (shown | shown_added) - shown_removed


def _cases():
    """Every case: its conditions, its base, and the tools it lists and shows."""
    expected = {"chat": (CHAT_LISTED, CHAT_SHOWN)}
    for base in ("job", "scheduled"):
        expected[base] = _apply(CHAT_LISTED, CHAT_SHOWN, BASE_CHANGES[base])
    cases = {base: (setup, None, *expected[base]) for base, setup in BASES.items()}
    for base, setup in BASES.items():
        for key, value in FLIPS.items():
            if setup[key] != value:
                changes = FLIP_CHANGES[base].get(key, FLIP_CHANGES["chat"][key])
                cases[f"{base}, {key}={value}"] = ({**setup, key: value}, base, *_apply(*expected[base], changes))
    for name, (setup, changes) in EXTRA.items():
        base = name.split(",")[0]
        cases[name] = (setup, base, *_apply(*expected[base], changes))
    return cases


CASES = _cases()
# effect, then the traits that are true, then its own gate
TRAITS = {
    "web_search": "read parallel outside replay_safe", "web_extract": "read parallel outside replay_safe",
    "render_chart": "read replay_safe", "recall": "read parallel outside", "remember": "local_write",
    "conversation_search": "external_write outside", "memory_note": "external_write",
    "task_progress": "read parallel outside", "delegate_work": "read outside", "update_plan": "read",
    "ask_user_choice": "external_write", "start_background_work": "local_write", "background_status": "read parallel",
    "stop_background_work": "local_write", "browser_open": "read outside", "browser_look": "read outside",
    "browser_back": "read outside", "browser_click": "external_write outside", "browser_type": "external_write outside",
    "browser_select": "external_write outside", "browser_press": "external_write outside",
    "mac_list_shortcuts": "read parallel", "mac_run_shortcut": "external_write", "mac_applescript": "external_write",
    "desktop_apps": "read", "desktop_access": "external_write", "desktop_look": "read",
    "desktop_click": "external_write", "desktop_type": "external_write", "desktop_select": "external_write",
    "desktop_scroll": "external_write", "desktop_open": "external_write", "desktop_batch": "external_write",
    "desktop_menu": "external_write", "desktop_press": "external_write", "desktop_takeover": "external_write",
    "read_skill": "read parallel replay_safe", "propose_plan_change": "external_write",
    "find_capability": "external_write outside", "propose_capability": "external_write", "create_skill": "local_write",
    "import_memories": "local_write", "verify": "local_write outside", "whats_new": "read parallel",
    "my_status": "read parallel", "list_my_capabilities": "read parallel",
    "read_file": "read parallel outside gate=file_arguments", "list_dir": "read parallel",
    "search_files": "read parallel outside", "write_file": "local_write saves gate=file_arguments_then_write",
    "edit_file": "local_write saves gate=workspace_write", "scan_local_network": "external_write",
    "ssh_probe": "external_write", "enroll_node": "external_write gate=enrol",
    "ssh_run": "external_write gate=remote_command", "list_nodes": "read parallel",
    "schedule_task": "external_write gate=schedule", "list_my_tasks": "read parallel", "cancel_task": "external_write",
    "run_command": "external_write gate=check", "attach_file": "local_write",
}


def _mac(monkeypatch, case):
    def setting(result):
        async def read(_db):
            return result
        return read

    monkeypatch.setattr(sys, "platform", case["platform"])
    monkeypatch.setattr(task_service, "current", lambda: TASK if case["task"] else None)
    monkeypatch.setattr(background_jobs, "inside_job", lambda: case["job"])
    monkeypatch.setattr(permissions, "current_asker", lambda: object() if case["asker"] else None)
    monkeypatch.setattr(hands_tools, "_scheduled_run", lambda: object() if case["scheduled"] else None)
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: case["hands"])
    monkeypatch.setattr(agent_browser, "available", lambda: case["browser"])
    monkeypatch.setattr(personal_context, "current", lambda: types.SimpleNamespace(
        project_id=7 if case["project"] else None, conversation_id="c1", query=""))
    monkeypatch.setattr(settings_service, "workspace_dir",
                        setting(Path("/workspace-for-the-table") if case["workspace"] else None))
    monkeypatch.setattr(settings_service, "workspace_is_default", setting(case["own_folder"]))
    monkeypatch.setattr(settings_service, "default_read_enabled", setting(case["default_read"]))
    monkeypatch.setattr(settings_service, "lan_discovery_enabled", setting(case["lan"]))
    monkeypatch.setattr(settings_service, "ssh_enabled", setting(case["ssh"]))
    monkeypatch.setattr(settings_service, "shell_enabled", setting(case["shell"]))
    monkeypatch.setattr(ssh_nodes, "list_nodes", setting([object()] if case["enrolled"] else []))
    monkeypatch.setattr(supervisor, "ready_now", lambda _id, _state: case["mcp"])

    async def skills(_limit=80):
        return "- weekly — Weekly report: every Friday" if case["skills"] else ""
    monkeypatch.setattr(arslan, "_skill_index", skills)


@pytest.fixture
async def _an_mcp_server(turn_db):
    """One ready MCP server with one tool, so the table has one."""
    async with turn_db() as db:
        db.add(Toolset(key="mcp_1", name="server", description="d", tier="safe", status="wired"))
        await db.flush()
        db.add(MCPServer(id=1, label="server", command="x", args=[], env=None, status="connected", host_allowed=True,
                         state="ready"))
        db.add(Tool(key="mcp_1__lookup", toolset_key="mcp_1", description="Look something up.", tier="safe",
                    status="wired", input_schema={"type": "object", "properties": {"id": {"type": "string"}}}))
        await db.commit()


async def _table(monkeypatch, case):
    with monkeypatch.context() as patch:
        _mac(patch, case)
        every = await arslan._every_tool()
        shown = await arslan._arslan_tools()
    return every, [tool["key"] for tool in shown]


@pytest.mark.parametrize("name", list(CASES))
async def test_each_case_offers_its_tools_with_their_traits(name, monkeypatch, _an_mcp_server):
    setup, _base, listed, shown = CASES[name]
    every, shown_keys = await _table(monkeypatch, setup)
    keys = [tool["key"] for tool in every]
    assert set(keys) == listed, f"listed + {sorted(set(keys) - listed)} - {sorted(listed - set(keys))}"
    order = [tool.name for tool in tool_defs.TOOLS]
    assert keys == [key for key in order if key in listed] + sorted(listed - set(order)), "the order changed"
    resident = [key for key in keys if key in shown]
    assert shown_keys == resident + ["find_tools", "use_tool"], f"shown {shown_keys}"
    for tool in tool_defs.TOOLS:
        if tool.name in listed:
            traits = tool.traits
            stated = " ".join([traits.effect, *(trait for trait in ("parallel", "outside", "replay_safe", "saves")
                                                if getattr(traits, trait)),
                               *([f"gate={tool.gate.__name__}"] if tool.gate else [])])
            assert stated == TRAITS[tool.name], f"{tool.name}: {stated}"


def _words(every):
    return json.dumps([every, tool_loop._native_tool_schemas(every, allow_escalation=True)], sort_keys=True)


@pytest.mark.parametrize("flip", [name for name, (_setup, base, *_) in CASES.items() if base == "chat"
                                  and name.count("=") == 1])
async def test_each_condition_changes_the_table(flip, monkeypatch, _an_mcp_server):
    """A flip that changes no name changes the words: the condition is still read."""
    every, _shown = await _table(monkeypatch, CHAT)
    flipped, _shown = await _table(monkeypatch, CASES[flip][0])
    assert _words(flipped) != _words(every)


def _fields(schema, path=""):
    """A parameter schema as the lines that matter to a call: each parameter's path, type, whether it is required, and
    its enum. Nested objects and array items are walked, so a change anywhere shows as the line it changed."""
    lines = []
    required = set(schema.get("required") or [])
    for name, prop in (schema.get("properties") or {}).items():
        where = f"{path}{name}"
        kind = prop.get("type", "any")
        line = f"{where}: {'|'.join(kind) if isinstance(kind, list) else kind}"
        items = prop.get("items") if isinstance(prop.get("items"), dict) else None
        if items is not None:
            line += f" of {items.get('type', 'any')}"
        if name in required:
            line += " required"
        for holder, label in ((prop, "enum"), (items or {}, "items enum")):
            if "enum" in holder:
                line += f" {label}=" + "|".join(str(value) for value in holder["enum"])
        lines.append(line)
        if prop.get("type") == "object":
            lines += _fields(prop, where + ".")
        if items is not None and items.get("type") == "object":
            lines += _fields(items, where + "[].")
    return lines


SCHEMAS = Path(__file__).parent / "tool_offer_schemas.json"
REGENERATE = "ARSLAN_UPDATE_TOOL_SCHEMAS=1 pytest tests/server/test_tool_offer_table.py -k parameters"


async def test_every_tools_parameters_are_as_pinned(monkeypatch, _an_mcp_server):
    """What each tool sends as its parameters, in every case, is the same and is what `tool_offer_schemas.json` says.
    A changed type, required field, enum or name fails here, naming the tool and the line."""
    seen: dict[str, list[str]] = {}
    for name, (setup, _base, _listed, _shown) in CASES.items():
        every, _shown_keys = await _table(monkeypatch, setup)
        for schema in tool_loop._native_tool_schemas(every, allow_escalation=True):
            tool, fields = schema["function"]["name"], sorted(_fields(schema["function"]["parameters"]))
            assert seen.setdefault(tool, fields) == fields, f"{tool}'s parameters differ in {name}"
    if os.environ.get("ARSLAN_UPDATE_TOOL_SCHEMAS") == "1":
        SCHEMAS.write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    pinned = json.loads(SCHEMAS.read_text(encoding="utf-8"))
    drift = {tool: {"now": sorted(set(seen.get(tool, [])) - set(pinned.get(tool, []))),
                    "pinned": sorted(set(pinned.get(tool, [])) - set(seen.get(tool, [])))}
             for tool in sorted(set(seen) | set(pinned)) if seen.get(tool) != pinned.get(tool)}
    assert not drift, (f"tool parameters changed: {json.dumps(drift, indent=1)}\nIf you meant it, regenerate and "
                       f"commit the JSON, so the diff shows the change: {REGENERATE}")


def test_every_offered_tool_has_its_traits_stated_here():
    offered = set().union(*(listed for _setup, _base, listed, _shown in CASES.values())) - {"mcp_1__lookup"}
    assert offered == set(TRAITS) == {tool.name for tool in tool_defs.TOOLS}
