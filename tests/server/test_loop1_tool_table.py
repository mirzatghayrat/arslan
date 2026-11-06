"""LOOP1 L0: the tool table as a request and a run see it, for every condition that changes it.

While the tools move into one object per tool, the table must stay byte-identical. Other lanes change descriptions
during that time, so nothing here is pinned to a fixture: each slice's PR dumps the table on its base and on its head and
gives both hashes.

LOOP1_TABLE_OUT=/some/file pytest tests/server/test_loop1_tool_table.py -s

The dump holds, per case: the order `_every_tool` lists the tools in (find_tools' tie-break), the table a request is
shown, and every schema it sends. It also holds the hash of the prompt's stable prefix, for slice e.

Temporary: DELETE-BY: v0.1.64, with LOOP1's slice z (docs/plans/0164/LOOP1-agent-loop.md).
"""
import hashlib
import json
import os
import sys
import types
from pathlib import Path

import pytest

from server.db.models import MCPServer, Tool, Toolset
from server.orchestrator import arslan, tool_loop
from server.registry import hands_tools
from server.services import agent_browser, background_jobs, permissions, personal_context, settings_service, ssh_nodes, task_service
from server.mcp import supervisor
from tests.server.test_loop1_pinned_turns import _booted, _database  # noqa: F401 — the fixtures

WORKSPACE = Path("/workspace-for-the-dump")
TASK = types.SimpleNamespace(closed=False)
# A chat turn on a Mac, with everything switched on that a default install has.
CHAT = dict(platform="darwin", task=True, job=False, asker=True, scheduled=False, browser=True, hands=True, skills=True,
            project=False, workspace=True, own_folder=True, default_read=True, lan=False, ssh=False, enrolled=False,
            shell=True, mcp=True)
BASES = {"chat": CHAT, "job": {**CHAT, "job": True}, "scheduled": {**CHAT, "asker": False, "scheduled": True}}
FLIPS = {"platform": "linux", "task": False, "job": True, "asker": False, "scheduled": True, "browser": False,
         "hands": False, "skills": False, "project": True, "workspace": False, "own_folder": False,
         "default_read": False, "lan": True, "ssh": True, "shell": False, "mcp": False}


def _cases():
    cases = {}
    for base, setup in BASES.items():
        cases[base] = setup
        for key, value in FLIPS.items():
            if setup[key] != value:
                cases[f"{base}, {key}={value}"] = {**setup, key: value}
    cases["chat, ssh=True, enrolled=True"] = {**CHAT, "ssh": True, "enrolled": True}
    cases["chat, no workspace, closed folders"] = {**CHAT, "workspace": False, "default_read": False}
    cases["job, chosen folder"] = {**BASES["job"], "own_folder": False}
    return cases


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
    monkeypatch.setattr(settings_service, "workspace_dir", setting(WORKSPACE if case["workspace"] else None))
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


async def _table():
    every = await arslan._every_tool()
    shown = await arslan._arslan_tools()
    return {"listed": [tool["key"] for tool in every],
            "shown": [tool["key"] for tool in shown],
            "schemas": tool_loop._native_tool_schemas(every, allow_escalation=True),
            "params_of_mcp": [tool_loop._tool_params(tool) for tool in every if tool["key"].startswith("mcp_")]}


async def _dump(monkeypatch, database) -> dict:
    async with database() as db:
        db.add(Toolset(key="mcp_1", name="server", description="d", tier="safe", status="wired"))
        await db.flush()
        db.add(MCPServer(id=1, label="server", command="x", args=[], env=None, status="connected", host_allowed=True,
                         state="ready"))
        db.add(Tool(key="mcp_1__lookup", toolset_key="mcp_1", description="Look something up.", tier="safe",
                    status="wired", input_schema={"type": "object", "properties": {"id": {"type": "string"}}}))
        await db.commit()
    dump = {"answer prefix sha256": hashlib.sha256(arslan._ANSWER_STABLE_PREFIX.encode()).hexdigest()}
    for name, case in _cases().items():
        with monkeypatch.context() as patch:
            _mac(patch, case)
            dump[name] = await _table()
    return dump


async def test_the_table_for_every_condition(monkeypatch, _database):  # noqa: F811
    dump = await _dump(monkeypatch, _database)
    text = json.dumps(dump, ensure_ascii=False, indent=1, sort_keys=True)
    out = os.environ.get("LOOP1_TABLE_OUT")
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(f"\nLOOP1 table: {len(dump) - 1} cases, sha256 {hashlib.sha256(text.encode()).hexdigest()}")
    for name, table in dump.items():
        if name != "answer prefix sha256":
            names = [schema["function"]["name"] for schema in table["schemas"]]
            assert len(names) == len(set(names)), f"a tool twice in {name}"
    flat = {name: json.dumps(table, sort_keys=True) for name, table in dump.items()}
    same = {key for key, value in FLIPS.items() if flat[f"chat, {key}={value}"] == flat["chat"]}
    assert same == set(), "a condition that changes nothing isn't exercising what it names"


@pytest.mark.parametrize("key", ["web_search", "run_command", "write_file"])
async def test_the_dump_sees_real_tools(key, monkeypatch, _database):  # noqa: F811
    _mac(monkeypatch, CHAT)
    assert key in (await _table())["listed"]
