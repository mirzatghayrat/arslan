"""The supervisor against real stdio servers (0.1.61 PR 4 review C2, C3, I6). `real_mcp` lifts
the spawn guard and nothing else: these run on CI and on the Mac."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from server import crypto
from server.db.models import MCPServer, Tool
from server.mcp import session
from server.mcp import supervisor as sm

pytestmark = pytest.mark.real_mcp
SERVER = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


@pytest.fixture
async def sup(execution_db, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sm, "RELIST_DEBOUNCE_S", 0.05)
    supervisor = sm.Supervisor()
    supervisor.maker = execution_db
    supervisor.start(run_loops=False)
    yield supervisor
    await supervisor.stop()
    await session.manager.aclose_all()


async def _seed(maker, mode, **env):
    async with maker() as db:
        db.add(MCPServer(id=1, label="fake", command=sys.executable, args=[str(SERVER), mode],
                         env=crypto.encrypt(json.dumps(env)), status="registered", state="starting"))
        await db.commit()


async def test_list_changed_adds_the_new_tool_without_a_restart(sup):
    await _seed(sup.maker, "list_changed")
    result = await sup.restart(1)
    assert result.state == "ready" and [t["name"] for t in result.tools] == ["a"]
    names = []
    for _ in range(60):
        async with sup.maker() as db:
            rows = (await db.execute(select(Tool).where(Tool.toolset_key == "mcp_1"))).scalars().all()
            names = sorted(t.external_name for t in rows)
        if names == ["a", "b"]:
            break
        await asyncio.sleep(0.05)
    assert names == ["a", "b"]
    async with sup.maker() as db:
        assert (await db.get(Tool, "mcp_1__b")).annotations == {"destructiveHint": True}
        assert (await db.get(Tool, "mcp_1__a")).annotations == {"readOnlyHint": True, "title": "Tool A"}


async def test_a_crash_is_failed_with_its_stderr_line(sup):
    await _seed(sup.maker, "crash_with_stderr")
    result = await sup.restart(1)
    first, *rest = result.last_error.splitlines()
    assert result.state == "failed"
    assert first == "the server exited during start — see its log below"
    assert "Error: REA_TOKEN is not set" in rest


async def test_a_program_that_prints_usage_is_parked_as_not_mcp(sup):
    await _seed(sup.maker, "usage_exit")
    result = await sup.restart(1)
    assert result.state == "parked" and result.last_error.startswith(sm.NOT_MCP_LINE)


async def test_a_slow_start_is_a_timeout_within_its_budget(sup, monkeypatch):
    await _seed(sup.maker, "slow_init", SLOW_INIT_S="3")
    monkeypatch.setattr(sm, "budget_for", lambda row, tool_count, *, fetched=False: 0.5)
    result = await sup.restart(1)
    assert result.state == "failed" and result.last_error.startswith("did not start within 0.5 s")
    monkeypatch.setattr(sm, "budget_for", lambda row, tool_count, *, fetched=False: 10.0)
    assert (await sup.restart(1)).state == "ready"


async def test_the_servers_own_secret_never_reaches_last_error(sup):
    await _seed(sup.maker, "echo_then_crash", FAKE_SECRET="s3cr3t-value-123")
    result = await sup.restart(1)
    assert "token is ****" in result.last_error and "s3cr3t" not in result.last_error
    async with sup.maker() as db:
        assert "s3cr3t" not in (await db.get(MCPServer, 1)).last_error
