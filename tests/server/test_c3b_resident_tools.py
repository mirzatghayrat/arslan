"""C3b: tools nobody used leave the table every request carries (card C3; ⓪Plan's Q2–Q4 and the SSH call).

- **Not resident** (0 calls in 30 days): the browser's back, click, type, select and press,
  `delegate_work` and `propose_capability`. `_arslan_tools()` no longer carries them. `_every_tool()`
  still defines them, and K7 makes them reachable on demand from there. Until K7, a job cannot act in
  the browser and `list_my_capabilities` does not list them. If K7 has not merged when R63's candidate
  is cut, C3b is reverted first.
- **SSH with no enrolled machine** offers `ssh_probe` and `enroll_node` only. Enrolling pins the host key
  before a first command runs, and the Capabilities page says the same. ssh_run itself works on any
  host, so this changes first use. ⓪Plan's call (A) on the user's card U3.
- `suggest_connector` is gone (C9b), and `run_python`, `create_skill` and `propose_plan_change`
  were never resident; only the last is pinned here.
"""
import sys

import pytest

from server.db.models import Setting
from server.orchestrator import arslan
from server.registry import hands_tools
from server.services import agent_browser, background_jobs, capability_list, ssh_nodes, task_service

DEMOTED = {"browser_back", "browser_click", "browser_type", "browser_select", "browser_press",
           "delegate_work", "propose_capability"}


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(agent_browser, "available", lambda: True)
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: True)
    monkeypatch.setattr(task_service, "current", lambda: object())


async def _keys(fn, *, job=False) -> set[str]:
    token = background_jobs._inside_job.set("job-1") if job else None
    try:
        return {t["key"] for t in await fn()}
    finally:
        if token is not None:
            background_jobs._inside_job.reset(token)


@pytest.mark.parametrize("job", [False, True])
async def test_the_demoted_tools_are_not_carried_but_still_defined(execution_db, mac, job):
    resident, every = await _keys(arslan._arslan_tools, job=job), await _keys(arslan._every_tool, job=job)
    assert not DEMOTED & resident
    assert {"browser_open", "browser_look"} <= every - resident   # K7: on demand as well
    expected = DEMOTED if job else DEMOTED - {"browser_click", "browser_type", "browser_select", "browser_press"}
    assert expected <= every
    assert not DEMOTED & arslan.RESIDENT          # K7 keeps them on demand (find_tools / use_tool)


async def test_a_chat_turn_is_still_told_where_page_actions_happen(execution_db, mac):
    desc = {t["key"]: t["description"] for t in await arslan._callable_tools()}
    assert "To click, type or submit on a page, start background work" in desc["browser_open"]


async def test_run_python_create_skill_and_project_proposals_are_not_resident(execution_db, mac):
    keys = await _keys(arslan._every_tool)
    assert not {"run_python", "create_skill", "propose_plan_change"} & keys


async def _ssh_on(execution_db, *, machines: int):
    async with execution_db() as db:
        db.add(Setting(key="ssh_enabled", value="true"))
        await db.commit()
        for i in range(machines):
            await ssh_nodes.enroll(db, name=f"box{i}", host=f"192.168.1.{10 + i}", username="me",
                                   host_keys=["ssh-ed25519 AAAA"], fingerprints=["SHA256:x"])


@pytest.mark.parametrize("machines, offered", [
    (0, {"ssh_probe", "enroll_node"}),
    (1, {"ssh_probe", "enroll_node", "ssh_run", "list_nodes"}),
])
async def test_ssh_offers_running_only_once_a_machine_is_enrolled(execution_db, machines, offered, monkeypatch):
    from server.registry import executors
    monkeypatch.setattr(executors, "AsyncSessionLocal", execution_db)   # the page's search row reads it by name
    await _ssh_on(execution_db, machines=machines)
    ssh_keys = {"ssh_probe", "ssh_run", "list_nodes", "enroll_node"}
    assert await _keys(arslan._callable_tools) & ssh_keys == offered         # K7: reachable
    row = next(r for r in await capability_list.capabilities() if r["key"] == "ssh")
    assert set(row["tools"]) == offered


async def test_enroll_node_says_to_enrol_before_running_commands(execution_db):
    await _ssh_on(execution_db, machines=0)
    desc = {t["key"]: t["description"] for t in await arslan._callable_tools()}
    assert "before running commands" in desc["enroll_node"]
