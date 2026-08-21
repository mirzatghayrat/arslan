"""Whether Arslan is offered SSH at all, and what an unattended turn can do with it.

The registration half mirrors LAN discovery and the workspace tools: off by
default, and when off the tool is ABSENT rather than present-and-refusing — a
tool that exists and always fails still shapes what the model plans to do.

The unattended half is the property the whole P3 plan rests on, so it is proven
against P2's real scheduler entry point rather than asserted about the source.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting

TOOLS = {"ssh_probe", "ssh_run"}


async def _wire(tmp_path, monkeypatch, **settings):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ssh.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    if settings:
        async with m() as s:
            for k, v in settings.items():
                s.add(Setting(key=k, value=v))
            await s.commit()
    return engine, m


@pytest_asyncio.fixture
async def keys_off(tmp_path, monkeypatch):
    engine, _ = await _wire(tmp_path, monkeypatch)
    from server.orchestrator.arslan import _arslan_tools
    yield {t["key"] for t in await _arslan_tools()}
    await engine.dispose()


@pytest_asyncio.fixture
async def keys_on(tmp_path, monkeypatch):
    engine, _ = await _wire(tmp_path, monkeypatch, ssh_enabled="true")
    from server.orchestrator.arslan import _arslan_tools
    yield {t["key"] for t in await _arslan_tools()}
    await engine.dispose()


async def test_default_off_means_the_tools_are_absent(keys_off):
    assert TOOLS & keys_off == set()
    assert "web_search" in keys_off               # unrelated tools unaffected


async def test_turning_it_on_offers_both(keys_on):
    assert TOOLS <= keys_on


async def test_the_lan_switch_does_not_also_grant_reach(tmp_path, monkeypatch):
    """Seeing a machine and logging into it are separate consents. Someone who
    opted into discovery has not thereby opted into execution."""
    engine, _ = await _wire(tmp_path, monkeypatch, lan_discovery_enabled="true")
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    await engine.dispose()
    assert "scan_local_network" in keys
    assert TOOLS & keys == set()


async def test_the_shell_switch_does_not_also_grant_reach(tmp_path, monkeypatch):
    engine, _ = await _wire(tmp_path, monkeypatch, orchestrator_shell_enabled="true")
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    await engine.dispose()
    assert "run_command" in keys
    assert TOOLS & keys == set()


# ── the unattended path, proven through the real scheduler entry point ─────────

async def test_a_scheduled_turn_cannot_ssh(tmp_path, monkeypatch):
    """Structural, not a rule: `run_arslan_turn` has no socket, so it passes no
    confirm callbacks, so the ssh gate's fail-closed branch is the only one
    reachable. This is the OpenClaw attack surface (persistence + unattended
    exec) closing by construction rather than by remembering."""
    engine, _ = await _wire(tmp_path, monkeypatch, ssh_enabled="true")
    from server.orchestrator import arslan as arslan_mod
    from server.orchestrator import tool_loop
    from server.services import scheduler, ssh_exec

    captured = {}
    probed = []

    async def _probe(host):
        probed.append(host)
        return {"ok": True, "host": host, "keys": ["k"], "fingerprints": ["fp"]}

    monkeypatch.setattr(ssh_exec, "probe", _probe)

    async def fake_answer(conversation_id, user_message, emit, **kw):
        captured["confirm_command"] = kw.get("confirm_command")
        # Whatever else the turn does, this is what an ssh attempt inside it hits.
        captured["result"] = await tool_loop._dispatch_tool(
            "ssh_run",
            {"host": "192.168.1.8", "user": "someone", "command": "git", "argv": ["status"]},
            "{}",
            resolve_tools=lambda: _tools(), emit=emit, tool_timeout_s=5,
            tool_trace=[], convo=[], confirm_command=kw.get("confirm_command"))
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_end", "message_id": 1})
        return {"ok": True}

    async def _tools():
        return [{"key": "ssh_run", "description": "remote"}]

    monkeypatch.setattr(arslan_mod, "_handle_answer", fake_answer)
    await scheduler.run_arslan_turn("conv-1", "check the other machine")
    await engine.dispose()

    assert captured["confirm_command"] is None, "an unattended turn has no way to ask"
    assert captured["result"]["ok"] is False
    assert "confirmation" in captured["result"]["error"]
    assert probed == [], "and it never reached the network on the way to being refused"


# ── replay sealing gets it for free, but prove it rather than assume ───────────

def test_ssh_is_not_replay_safe():
    from server.services import replay_safety
    assert not replay_safety.is_replay_safe("ssh_run")
    assert not replay_safety.is_replay_safe("ssh_probe")
    assert replay_safety.filter_replay_tools(
        [{"key": "ssh_run"}, {"key": "ssh_probe"}, {"key": "web_search"}]
    ) == [{"key": "web_search"}]


@pytest.mark.parametrize("key", ["ssh_probe", "ssh_run"])
def test_both_tools_have_an_executor_registered(key):
    from server.registry.executors import EXECUTORS
    assert EXECUTORS[key].key == key


# ── the executor re-checks the switch, not just registration ───────────────────

@pytest.mark.parametrize("key,args", [
    ("ssh_probe", {"host": "192.168.1.8"}),
    ("ssh_run", {"host": "192.168.1.8", "user": "someone",
                 "command": "git", "argv": ["status"]}),
])
async def test_the_executor_refuses_when_the_switch_is_off(tmp_path, monkeypatch, key, args):
    """Registration is not the only door. A tool list can go stale inside a long
    turn, and a direct dispatch skips registration entirely — so the switch is
    re-read where the work would actually happen. Without this, turning SSH off
    mid-conversation would leave a live capability behind."""
    engine, _ = await _wire(tmp_path, monkeypatch)          # switch absent = off
    from server.registry.executors import EXECUTORS
    from server.services import ssh_exec

    reached = []
    monkeypatch.setattr(ssh_exec, "probe", lambda h: reached.append(h))
    monkeypatch.setattr(ssh_exec, "run", lambda *a, **k: reached.append(a))

    result = await EXECUTORS[key].execute(args)
    await engine.dispose()
    assert result["ok"] is False
    assert "off" in result["error"]
    assert reached == [], "and it must not reach the network on its way to refusing"
