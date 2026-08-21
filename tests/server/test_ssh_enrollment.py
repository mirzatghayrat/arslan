"""Proposing and performing enrolment (spec P3c).

The division of labour is the safety argument, so it is what gets tested: the
TOOL only paints a card, and the WRITE only happens on a REST call the person's
click makes. There is deliberately no code path where Arslan calling a tool
enrols a machine — not a callback that could be forgotten, an absence of any
write on that path at all.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting
from server.orchestrator import tool_loop
from server.registry.executors import EXECUTORS
from server.services import ssh_exec, ssh_nodes

KEY = "192.168.1.8 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
FP = "256 SHA256:aaaa (ED25519)"
ARGS = {"host": "192.168.1.8", "user": "someone", "name": "studio"}


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'enrol.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(Setting(key="ssh_enabled", value="true"))
        await s.commit()
    yield m
    await engine.dispose()


@pytest.fixture
def probe_ok(monkeypatch):
    async def _probe(host):
        return {"ok": True, "host": host, "keys": [KEY], "fingerprints": [FP]}
    monkeypatch.setattr(ssh_exec, "probe", _probe)


async def _tools():
    return [{"key": "enroll_node", "description": "propose"}]


async def _dispatch(args, *, confirm=None, emit=None):
    return await tool_loop._dispatch_tool(
        "enroll_node", args, "{}", resolve_tools=_tools, emit=(emit or (lambda e: None)),
        tool_timeout_s=5, tool_trace=[], convo=[], confirm_command=confirm)


# ── the tool proposes and nothing else ─────────────────────────────────────────

async def test_the_tool_paints_a_card_and_enrols_nothing(maker, probe_ok):
    frames = []

    async def _confirm(c, a, **kw):        # present = there is somebody to ask
        return True

    r = await _dispatch(ARGS, confirm=_confirm, emit=frames.append)
    assert r["ok"] is True and r["proposed"] is True
    proposals = [f for f in frames if f.get("type") == "propose_enroll_node"]
    assert len(proposals) == 1
    card = proposals[0]
    assert card["host"] == "192.168.1.8" and card["name"] == "studio"
    assert card["fingerprints"] == [FP], "the card must show what the user has to check"

    async with maker() as s:
        assert await ssh_nodes.list_nodes(s) == [], "proposing must not enrol"


async def test_calling_the_executor_directly_cannot_enrol(maker, probe_ok):
    """The invariant stated as a test: there is no path on which this tool writes.
    Bypassing the tool loop entirely still enrols nothing."""
    r = await EXECUTORS["enroll_node"].execute(ARGS)
    assert r["ok"] is False
    async with maker() as s:
        assert await ssh_nodes.list_nodes(s) == []


async def test_an_unattended_turn_gets_no_card(maker, probe_ok):
    frames = []
    r = await _dispatch(ARGS, confirm=None, emit=frames.append)
    assert r["ok"] is False
    assert [f for f in frames if f.get("type") == "propose_enroll_node"] == []


async def test_an_unreachable_machine_is_not_proposed(maker, monkeypatch):
    async def _probe(host):
        return {"ok": False, "error": "no SSH service answered on 192.168.1.8:22"}
    monkeypatch.setattr(ssh_exec, "probe", _probe)
    frames = []

    async def _confirm(c, a, **kw):
        return True

    r = await _dispatch(ARGS, confirm=_confirm, emit=frames.append)
    assert r["ok"] is False and "no SSH service" in r["error"]
    assert [f for f in frames if f.get("type") == "propose_enroll_node"] == []


@pytest.mark.parametrize("bad,why", [
    ({"host": "nas.local", "user": "someone", "name": "studio"}, "not an address"),
    ({"host": "192.168.1.8", "user": "", "name": "studio"}, "no username"),
    ({"host": "192.168.1.8", "user": "someone", "name": ""}, "no name"),
])
async def test_bad_arguments_never_reach_a_card(maker, probe_ok, bad, why):
    frames = []

    async def _confirm(c, a, **kw):
        return True

    r = await _dispatch(bad, confirm=_confirm, emit=frames.append)
    assert r["ok"] is False, why
    assert [f for f in frames if f.get("type") == "propose_enroll_node"] == []


async def test_a_machine_already_enrolled_is_not_proposed_again(maker, probe_ok):
    async with maker() as s:
        await ssh_nodes.enroll(s, name="studio", host="192.168.1.8", username="someone",
                               host_keys=[KEY], fingerprints=[FP])
    frames = []

    async def _confirm(c, a, **kw):
        return True

    r = await _dispatch({"host": "192.168.1.8", "user": "someone", "name": "other"},
                        confirm=_confirm, emit=frames.append)
    assert r["ok"] is False and "already enrolled" in r["error"]
    assert frames == [] or [f for f in frames if f.get("type") == "propose_enroll_node"] == []


# ── the list tool ──────────────────────────────────────────────────────────────

async def test_list_nodes_reports_what_is_enrolled(maker):
    async with maker() as s:
        await ssh_nodes.enroll(s, name="studio", host="192.168.1.8", username="someone",
                               host_keys=[KEY], fingerprints=[FP])
    r = await EXECUTORS["list_nodes"].execute({})
    assert r["ok"] is True
    assert r["nodes"] == [{"name": "studio", "host": "192.168.1.8", "user": "someone"}]


async def test_list_nodes_refuses_when_the_switch_is_off(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'off.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    r = await EXECUTORS["list_nodes"].execute({})
    await engine.dispose()
    assert r["ok"] is False and "off" in r["error"]


# ── the tools are offered only behind the switch ───────────────────────────────

async def test_node_tools_are_absent_when_ssh_is_off(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'off2.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    await engine.dispose()
    assert {"enroll_node", "list_nodes"} & keys == set()


async def test_node_tools_are_offered_when_ssh_is_on(maker):
    """The other half. Without this, deleting the registration outright would
    leave the suite green — "absent when off" is satisfied by "absent always"."""
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    assert {"enroll_node", "list_nodes"} <= keys
