"""S1 (R6): an MCP call is approved by what its server says the tool does (card S1; ⓪Plan's Q5/Q6/(i)).

Before S1 a call went straight to the server: no card, no ledger row. Now, decided in the executor
between the ready check and the call, from the hints discovery stored on the tool's row:
- **read-only** (`readOnlyHint: true`): it runs, and one ledger row says the mode let it;
- **destructive** (`destructiveHint: true`): the `destructive` card, this time only, every time — red on
  the web, never answered from the island, "delete" on the phone;
- **anything else, no hints included**: an `mcp_tool` card, this time or for this conversation.
- **Nobody to ask** (a scheduled run): only read-only runs; anything else is refused by policy, with a
  ledger row the Inbox lists, even if this conversation granted it (U14 a).
A refusal never reached the server: `executed: False`, Arslan's own words (`external: False`), and a
known failure, not something the user must check.
The executor finds its tool by the row's real key (names over 50 characters are hashed in the key).
"""
import json

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ApprovalEvent, Base, MCPServer, Tool, Toolset
from server.mcp import discovery, executor, session
from server.services import approvals, permission_store, permissions, task_service
from server.services import personal_context as pc
from server.registry.executors import resolve_executor

LONG = "x" * 60
LONG_KEY = discovery.mcp_tool_key(2, LONG)
HINTS = {"read_file": {"readOnlyHint": True}, "delete_file": {"readOnlyHint": False, "destructiveHint": True},
         "write_file": None, LONG: {"readOnlyHint": True}, "frobnicate": {"readOnlyHint": True},
         "wipe": {"readOnlyHint": True, "destructiveHint": True}}


class _Text:
    def __init__(self, t):
        self.type, self.text = "text", t


class _Result:
    def __init__(self, content):
        self.content, self.isError = content, False


class Asker:
    def __init__(self, *answers):
        self.answers, self.frames = list(answers), []

    async def __call__(self, frame):
        self.frames.append(frame)
        return self.answers.pop(0)


def yes(scope="once"):
    return {"approved": True, "scope": scope, "note": "", "by": "mac"}


def no():
    return {"approved": False, "scope": None, "note": "", "by": "mac"}


@pytest_asyncio.fixture
async def mcp(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's1.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    permission_store._reset_for_tests()
    permissions._reset_for_tests()
    async with maker() as s:
        s.add(MCPServer(id=2, label="files", command="x", args=[], env=None, status="connected", state="ready"))
        s.add(Toolset(key="mcp_2", name="files", description="d", tier="orchestrator", status="registered"))
        for name, hints in HINTS.items():
            s.add(Tool(key=discovery.mcp_tool_key(2, name), toolset_key="mcp_2", description=name, tier="orchestrator",
                       status="wired", input_schema={}, external_name=name, annotations=hints))
        await s.commit()
    calls = []

    async def call_tool(server, name, args):
        calls.append((name, args))
        return _Result([_Text("done")])
    monkeypatch.setattr(session.manager, "call_tool", call_tool)
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="conv-1")):
        yield maker, calls
    await engine.dispose()


async def _run(key, args=None):
    return await (await resolve_executor(key)).execute(args or {"path": "/a"})


async def _rows(maker):
    async with maker() as db:
        return (await db.execute(sa.select(ApprovalEvent).order_by(ApprovalEvent.id))).scalars().all()


def test_the_hints_read_as_the_card_says():
    assert discovery.read_only({"readOnlyHint": True}) and not discovery.read_only(None)
    assert discovery.destructive({"destructiveHint": True}) and not discovery.destructive(None)
    contradictory = {"readOnlyHint": True, "destructiveHint": True}    # the safer reading wins (⓪Plan's review)
    assert discovery.destructive(contradictory) and not discovery.read_only(contradictory)
    assert not discovery.destructive({})                      # no hints: "other", not the spec's default (Q5)


async def test_a_read_only_tool_runs_without_a_card_and_is_counted(mcp):
    maker, calls = mcp
    asker = Asker()
    with permissions.asking_with(asker):
        out = await _run("mcp_2__read_file")
    assert out["ok"] is True and calls == [("read_file", {"path": "/a"})] and asker.frames == []
    [row] = await _rows(maker)
    assert (row.kind, row.decided_by, row.decision) == ("mcp_tool", "mode", "allow")


async def test_a_destructive_tool_asks_every_time_and_only_for_this_time(mcp):
    maker, calls = mcp
    asker = Asker(yes(), yes())
    with permissions.asking_with(asker):
        await _run("mcp_2__delete_file")
        await _run("mcp_2__delete_file")
    assert len(asker.frames) == 2 and len(calls) == 2
    frame = asker.frames[0]
    assert frame["options"] == ["once"] and frame["perm_kind"] == "destructive"
    assert approvals.island_may_answer(frame) is False
    assert "files" in frame["title"] and "delete_file" in frame["title"]


async def test_any_other_tool_asks_and_a_yes_for_this_conversation_stands(mcp):
    maker, calls = mcp
    asker = Asker(yes("conversation"))
    with permissions.asking_with(asker):
        await _run("mcp_2__write_file")
        await _run("mcp_2__write_file")
    assert len(asker.frames) == 1 and len(calls) == 2
    assert asker.frames[0]["options"] == ["once", "conversation"] and asker.frames[0]["perm_kind"] == "mcp_tool"
    assert json.loads(asker.frames[0]["detail"]) == {"path": "/a"}
    assert [(r.decided_by, r.decision) for r in await _rows(maker)] == [("user", "allow"), ("grant", "allow")]


async def test_a_refusal_never_reaches_the_server_and_is_a_known_failure(mcp):
    maker, calls = mcp
    with permissions.asking_with(Asker(no())):
        out = await _run("mcp_2__write_file")
    assert calls == [] and out["ok"] is False and out["executed"] is False and out["external"] is False
    assert task_service.known_local_failure("mcp_2__write_file", {"path": "/a"}, out) is True


async def test_with_nobody_to_ask_only_read_only_runs_even_with_a_grant(mcp):
    """A scheduled run (no card surface): read-only is allowed before the refusal is reached (⓪Plan (i));
    anything else is refused by policy, even after this conversation granted it."""
    maker, calls = mcp
    with permissions.asking_with(Asker(yes("conversation"))):
        await _run("mcp_2__write_file")                         # the grant
    calls.clear()
    ran = await _run("mcp_2__read_file")
    refused = await _run("mcp_2__write_file")
    destroyed = await _run("mcp_2__delete_file")
    assert ran["ok"] is True and calls == [("read_file", {"path": "/a"})]
    assert refused["ok"] is False and refused["executed"] is False and destroyed["ok"] is False
    rows = await _rows(maker)
    assert [(r.decided_by, r.decision) for r in rows[1:]] == [("mode", "allow"), ("policy", "deny"), ("policy", "deny")]
    assert not (rows[2].extra or {}).get(permissions.ALWAYS_KEY)   # no "Always" for an unattended refusal (Q2)


async def test_a_long_tool_name_finds_its_own_row(mcp):
    maker, calls = mcp
    assert len(LONG_KEY) <= 50 and LONG_KEY != f"mcp_2__{LONG}"
    with permissions.asking_with(Asker()):                       # read-only by its row: no card
        out = await _run(LONG_KEY)
    assert out["ok"] is True and calls == [(LONG, {"path": "/a"})]
    [row] = await _rows(maker)
    assert row.target == LONG_KEY                                # the ledger (and any grant) use the real key


async def test_arguments_longer_than_a_card_shows_are_refused_never_cut(mcp):
    """⓪Plan's review: the card carries at most protocol.DETAIL_MAX characters, so padding would push the
    real target off it and the yes would cover arguments nobody saw."""
    from server.ws import protocol
    maker, calls = mcp
    padded = {"padding": "x" * 5000, "path": "/important"}
    asker = Asker(yes("conversation"))
    with permissions.asking_with(asker):
        out = await _run("mcp_2__write_file", padded)
        granted = await _run("mcp_2__write_file", {"path": "/a"})          # a short one cards, and is granted
        again = await _run("mcp_2__write_file", padded)                    # not even under the grant
    assert out["executed"] is False and out["code"] == "too_long_to_show" and again["code"] == "too_long_to_show"
    assert granted["ok"] is True and len(asker.frames) == 1 and calls == [("write_file", {"path": "/a"})]
    assert len(json.dumps(padded)) > protocol.DETAIL_MAX >= len(asker.frames[0]["detail"])


async def test_contradictory_hints_get_the_destructive_card(mcp):
    maker, calls = mcp
    asker = Asker(yes())
    with permissions.asking_with(asker):
        await _run("mcp_2__wipe")
    assert asker.frames[0]["perm_kind"] == "destructive" and asker.frames[0]["options"] == ["once"]


async def test_a_check_that_fails_is_a_refusal_that_never_reached_the_server(mcp, monkeypatch):
    maker, calls = mcp

    async def broken(*a, **k):
        raise RuntimeError("ledger unavailable")
    monkeypatch.setattr(permissions, "decide", broken)
    with permissions.asking_with(Asker()):
        out = await _run("mcp_2__write_file")
    assert calls == [] and out["ok"] is False and out["executed"] is False


def test_an_mcp_tool_is_never_offered_always():
    req = permissions.Request(kind="mcp_tool", target="mcp_2__write_file", title="t", always_label="files")
    assert "always" not in permissions.options_for(req)


async def test_a_read_only_mcp_tool_is_a_read(mcp):
    assert await task_service.effect_of("mcp_2__frobnicate", {}) == "read"     # by its hint, not its name
    assert await task_service.effect_of("mcp_2__write_file", {}) == "external_write"


def test_a_card_can_wait_its_whole_window():
    assert executor.MCPProxyExecutor.timeout_s >= approvals.TIMEOUT_S + executor.CALL_BOUND_S


def test_a_refusal_is_not_counted_as_the_tool_failing():
    """⓪Plan's review: two refusals told the model "this MCP tool has failed 2 times"."""
    from server.orchestrator import tool_loop
    counts: dict = {}
    refused = {"ok": False, "external": False, "executed": False, "code": "declined", "error": "no"}
    failed = {"ok": False, "error": "[MCP files · stdio] boom"}
    for result in (refused, refused, failed, failed):
        tool_loop._record_tool_result("mcp_2__write_file", {}, dict(result), lambda e: None, [], "", [],
                                      mcp_fail_counts=counts)
    assert counts == {"mcp_2__write_file": 2}
