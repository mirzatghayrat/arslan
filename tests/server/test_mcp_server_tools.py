import json

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, MCPServer, Run, Spawn
from server.registry.seeder import seed_registry_with
from server.mcp_server import tools

BODY_MARKER = "SUPERSECRET_OUTPUT_BODY_MARKER"
# get_run_status fields — the spec's fixed metadata list (spec §4). eval_verdict is the
# honest mapping of the judged outcome (Run has no single eval_verdict column).
ALLOWED_RUN_KEYS = {
    "run_id", "spawn_id", "spawn_name", "status", "kind", "model", "provider",
    "tokens_in", "tokens_out", "started_at", "ended_at", "eval_verdict",
}
SPAWN_KEYS = {
    "id", "name", "domain", "capabilities", "generation_level", "is_default",
    "has_active_chat", "equipment",
}
BANNED_KEYS = {
    "final_output", "answer", "system_prompt", "injected_kb", "injected_kb_sources",
    "error_text", "user_message", "trace", "content", "body",
    # MCPServer body-ish fields that must NEVER reach an external client (a url can
    # embed an api_key query param):
    "url", "last_error", "env", "command", "args",
}


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with m() as s:
        await seed_registry_with(s)
        # Spawn ORM columns: name, domain_category (NOT NULL), system_prompt (NOT NULL)
        # — there is NO `domain` column (SpawnOut.domain is a computed DTO field).
        s.add(Spawn(name="Alpha", domain_category="research", persona_role="analyst",
                    system_prompt=BODY_MARKER, capabilities=["web_search"]))
        # Seed one MCPServer so list_capabilities' mcp_servers list is non-empty (the
        # per-item allowlist assertion is then non-vacuous). BODY_MARKER lives in url +
        # last_error — fields that must NOT surface in list_capabilities.
        s.add(MCPServer(label="srv-marker", command="node",
                        url="http://x/" + BODY_MARKER, last_error=BODY_MARKER))
        s.add(Run(conversation_id="c1", spawn_id=1, spawn_name="Alpha",
                  user_message=BODY_MARKER, status="scored", kind="replay",
                  model="deepseek-v4-flash", provider="deepseek",
                  tokens_in=10, tokens_out=20, task_tokens=30,
                  overall_score=8.0, overall_badge="good",
                  final_output=BODY_MARKER, system_prompt=BODY_MARKER,
                  injected_kb=BODY_MARKER, error_text=BODY_MARKER))
        await s.commit()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    yield m
    await engine.dispose()


def _no_body(result):
    blob = json.dumps(result)
    assert BODY_MARKER not in blob, f"output body leaked: {result}"

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert k not in BANNED_KEYS, f"banned key {k} in {o}"
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(result)


async def test_list_spawns_metadata_only(maker):
    res = await tools.list_spawns()
    spawn = res["spawns"][0]
    assert spawn["name"] == "Alpha" and spawn["domain"] == "research"
    assert set(spawn.keys()) == SPAWN_KEYS           # EXACT per-item allowlist
    assert set(spawn["equipment"].keys()) == {"toolsets", "skills"}
    _no_body(res)


async def test_list_capabilities_labels_only(maker):
    res = await tools.list_capabilities()
    assert set(res.keys()) == {"builtin_tools", "mcp_servers", "skills"}
    for item in res["builtin_tools"]:
        assert set(item.keys()) == {"key", "description", "tier"}      # EXACT
    assert res["mcp_servers"], "fixture must seed at least one MCP server (non-vacuous guard)"
    for item in res["mcp_servers"]:
        assert set(item.keys()) == {"label", "status"}                 # EXACT — no url/last_error
    for item in res["skills"]:
        assert set(item.keys()) == {"key", "description"}              # EXACT
    _no_body(res)                                                       # marker seeded in url+last_error


async def test_get_run_status_by_run_id_is_metadata_only(maker):
    res = await tools.get_run_status(run_id=1)
    assert set(res.keys()) == ALLOWED_RUN_KEYS
    assert res["status"] == "scored" and res["eval_verdict"]["badge"] == "good"
    _no_body(res)


async def test_get_run_status_by_spawn_id(maker):
    res = await tools.get_run_status(spawn_id=1)
    assert res["spawn_id"] == 1 and len(res["runs"]) == 1
    assert set(res["runs"][0].keys()) == ALLOWED_RUN_KEYS
    _no_body(res)


async def test_get_run_status_unknown_id_is_structured_not_error(maker):
    assert await tools.get_run_status(run_id=99999) == {"found": False, "run_id": 99999}
    assert await tools.get_run_status() == {"found": False, "detail": "provide run_id or spawn_id"}


async def test_each_tool_emits_exactly_one_audit_line(maker, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="arslan.mcp_server.audit"):
        await tools.list_spawns()
        await tools.list_capabilities()
        await tools.get_run_status(run_id=1)
    audited = [r.getMessage() for r in caplog.records if r.name == "arslan.mcp_server.audit"]
    assert len(audited) == 3
    # audit.record's frozen log format is "mcp_audit tool=<name> status=..." (Task 3,
    # server/mcp_server/audit.py) — the tool name is a substring (e.g. "tool=list_spawns"),
    # never its own whitespace-split token, so this checks containment (same convention as
    # tests/server/test_mcp_audit.py's `"list_spawns" in msg`) rather than token-set membership.
    joined = " ".join(audited)
    assert all(name in joined for name in {"list_spawns", "list_capabilities", "get_run_status"})
