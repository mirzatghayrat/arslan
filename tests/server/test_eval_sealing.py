# tests/server/test_eval_sealing.py
#
# ── Task 5 audit: eval-context dispatch caller sweep ────────────────────────────────
# Goal: confirm EVERY eval-context dispatch caller is sealed by Task 3's structural
# no-override rule (dispatcher.dispatch: `if replay or is_hermetic_context(conversation_id):
# return await _dispatch_replay(...)`, server/orchestrator/dispatcher.py:576), and that the
# boundary is NOT over-sealed (real/scheduled conversation ids must stay live). Verdict for
# all three audited callers below: SEALED-BY-TASK-3 or OUT-OF-SCOPE. No production code
# change was required — this task adds only the audit record + the boundary test below.
#
# 1. server/api/discovery.py:33-34 `POST /discovery/evaluate` → discovery_service.evaluate_ref
#    (server/services/discovery_service.py:15) → github_eval.fetch_repo/fetch_readme +
#    mcp_suggest.classify_and_suggest (server/services/mcp_suggest.py:16, ONE non-tool-calling
#    adapter.chat() classification call). VERDICT: OUT OF SCOPE, not merely "intentionally
#    live" — this handler never calls dispatcher.dispatch/run_arm/tool_loop at all, so it has
#    no conversation_id and no dispatch surface for Task 3's rule to seal or over-seal. It is
#    a manual, auth-gated (require_auth), read-only "evaluate this GitHub repo as an MCP
#    candidate" endpoint — semantically unrelated to spawn/evolution eval. Confirmed via grep:
#    no "dispatch"/"conversation_id"/"run_arm"/"tool_loop" hits in discovery_service.py,
#    mcp_suggest.py, github_eval.py, or skill_suggest.py. No seal applicable; no change made.
#
# 2. server/services/evolution_loop.py `refresh_proposal` (:236-310) reaches dispatch only
#    via `replay_gate.run_gate(...)` at :275-277 → replay_gate.run_gate (server/services/
#    replay_gate.py:386-391) calls `replay_run.run_arm(...)` for BOTH the baseline and
#    candidate arms → replay_run.run_arm (server/services/replay_run.py:51-58) calls
#    `dispatcher.dispatch(conversation_id, ..., replay=True, ambient=ambient)` where
#    `conversation_id` defaults to `REPLAY_CONVERSATION_ID = "evolution-replay"`
#    (replay_run.py:24,52) — a member of `_HERMETIC_CONVERSATION_IDS`. Double-sealed: explicit
#    `replay=True` AND a hermetic-sentinel conversation_id. `refresh_proposal` has no other
#    dispatch call site. VERDICT: SEALED-BY-TASK-3 (already, via Task 4's run_arm routing).
#    No change needed.
#
# 3. server/orchestrator/dispatcher.py:614 `html_artifact.package_spawn_output(run_id, full)`
#    (run_id defaults to None per `dispatch()`'s signature, :532) sits on the LIVE branch of
#    `dispatch()`, AFTER the no-override hermetic check at :572-583 (`if replay or
#    is_hermetic_context(conversation_id): return await _dispatch_replay(...)`). Any dispatch
#    under an eval/replay sentinel OR replay=True returns from `_dispatch_replay` (:437-515)
#    before this line is ever reached. `_dispatch_replay` itself contains an explicit comment
#    at :495-497 ("Deliberately DO NOT call html_artifact.package_spawn_output with a real
#    run_id...") and has NO call to html_artifact anywhere in its body — confirmed by grep
#    (only the live branch at :614 calls it). VERDICT: SEALED-BY-TASK-3 (structurally
#    unreachable from a hermetic dispatch). No change needed.
#
# Boundary check (Step 2 below): the scheduler mints REAL conversation ids that must NOT be
# swept up as hermetic. Confirmed via grep "scheduled-" in server/services/scheduler.py: the
# actual literal is `f"scheduled-{task.id}"` / `f"scheduled-{task_id}"` (scheduler.py:330 and
# :480, used by `_fire` at :480,505 for a REAL `dispatcher.dispatch` via `_dispatch_recorded`)
# — i.e. "scheduled-42", NOT "scheduled-task-42". `test_scheduled_and_real_conversation_ids_
# are_not_hermetic` below pins the REAL format plus a near-miss variant, a real user id, and
# empty string as all non-hermetic.
import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base
from server.services import replay_safety
from server.services.replay_run import REPLAY_CONVERSATION_ID
from server.orchestrator import tool_loop


@pytest_asyncio.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    """Autouse, file-scoped DB isolation.

    The new test_dispatch_* tests (below) call dispatcher.dispatch() for a real
    conversation_id with no other DB setup; on the live branch that reaches
    memory.user_turn_count(), which reads server.db.session.AsyncSessionLocal
    directly (bypassing FastAPI's dependency injection some other tests override).
    Without this, those tests would hit whichever real DB ARSLAN_DATA_DIR happens
    to resolve to in the ambient environment and fail with "no such table" on a
    fresh checkout — unrelated to the behavior under test. Every other dispatcher
    test file in this suite (e.g. test_dispatcher.py's `maker` fixture) sets up an
    isolated schema-created engine the same way; this mirrors that convention as
    an autouse fixture so the given test bodies stay untouched.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'eval_seal.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    yield
    await engine.dispose()


def test_is_hermetic_context_matches_both_eval_sentinels():
    # Both eval sentinels are hermetic; a real conversation id and None are not.
    assert replay_safety.is_hermetic_context("evolution-eval") is True
    assert replay_safety.is_hermetic_context("evolution-replay") is True
    assert replay_safety.is_hermetic_context(REPLAY_CONVERSATION_ID) is True  # == "evolution-replay"
    assert replay_safety.is_hermetic_context("conv_abc123") is False
    assert replay_safety.is_hermetic_context(None) is False


def test_hermetic_set_covers_every_sentinel_a_dispatch_path_actually_uses():
    """Pin the sentinels against the LIVE dispatch paths, not against themselves.

    The old version of this test asserted `"evolution-eval" in _HERMETIC_CONVERSATION_IDS`
    — a tautology over a literal that no dispatch path uses (repo-wide grep: the string
    appears ONLY in replay_safety's own set). It could never fail. The real invariant is
    that the sentinel each eval/replay entry point dispatches under is a member.
    """
    from server.services.replay_run import REPLAY_CONVERSATION_ID

    assert REPLAY_CONVERSATION_ID in replay_safety._HERMETIC_CONVERSATION_IDS
    assert replay_safety.is_hermetic_context(REPLAY_CONVERSATION_ID) is True


# --------------------------------------------------------------------------- curation split


def test_should_not_curate_covers_the_eval_sentinels():
    """整理层: synthetic traffic must never be learned from."""
    assert replay_safety.should_not_curate("evolution-replay") is True
    assert replay_safety.should_not_curate("evolution-eval") is True


def test_should_not_curate_leaves_real_and_live_work_curatable():
    assert replay_safety.should_not_curate("conv_abc123") is False
    assert replay_safety.should_not_curate("scheduled-7") is False   # real work
    assert replay_safety.should_not_curate(None) is False


def test_curation_ids_must_never_enter_the_hermetic_set():
    """🔴 The split exists because is_hermetic_context is DUAL-purpose: besides marking
    synthetic traffic it makes tool_loop's throat refuse every non-replay-safe tool
    (tool_loop.py:335). Curation must be excluded from the corpus WITHOUT being sealed —
    it has to write. Anyone who "simplifies" the two predicates back into one, or adds a
    curation sentinel to the hermetic set, seals the curator's own writes; this test is
    the tripwire."""
    for cid in replay_safety._HERMETIC_CONVERSATION_IDS:
        assert cid.startswith("evolution-"), (
            "only evolution eval/replay sentinels may be hermetic — a curation/background "
            "id here would make tool_loop refuse the curator's own writes")
    assert replay_safety.should_not_curate is not replay_safety.is_hermetic_context


async def test_throat_refuses_nonsafe_tool_in_hermetic_context_even_if_resolver_leaks():
    """The backstop is independent of resolve_tools: even if resolve_tools LEAKS an MCP
    key into the live set (simulating a forgotten upstream filter), a hermetic
    conversation_id must make _dispatch_tool refuse it without executing."""
    executed = []

    async def leaky_resolve():
        # Deliberately leak a side-effecting MCP tool into the live set.
        return [{"key": "mcp_1__send_message"}, {"key": "web_search"}]

    # Monkeypatch resolve_executor so we can detect if execution is (wrongly) reached.
    import server.orchestrator.tool_loop as tl

    async def fake_resolve_executor(key):
        executed.append(key)
        class _E:
            async def execute(self, args):
                executed.append(("EXECUTED", key))
                return {"ok": True}
        return _E()

    orig = tl.resolve_executor
    tl.resolve_executor = fake_resolve_executor
    try:
        emitted = []
        out = await tool_loop._dispatch_tool(
            "mcp_1__send_message", {"to": "x"},
            json.dumps({"tool": "mcp_1__send_message", "args": {}}),
            resolve_tools=leaky_resolve, emit=lambda e: emitted.append(e),
            tool_timeout_s=5, tool_trace=[], convo=[{"role": "user", "content": "hi"}],
            conversation_id="evolution-eval")
    finally:
        tl.resolve_executor = orig

    assert out["ok"] is False
    assert "hermetic" in (out.get("error") or "").lower()
    assert ("EXECUTED", "mcp_1__send_message") not in executed  # never executed


async def test_throat_allows_safe_tool_in_hermetic_context():
    """A read-only builtin (web_search) is NOT blocked by the backstop in a hermetic
    context — it still resolves + executes normally."""
    import server.orchestrator.tool_loop as tl

    async def resolve():
        return [{"key": "web_search"}]

    async def fake_resolve_executor(key):
        class _E:
            async def execute(self, args):
                return {"ok": True, "results": []}
        return _E()

    orig = tl.resolve_executor
    tl.resolve_executor = fake_resolve_executor
    try:
        out = await tool_loop._dispatch_tool(
            "web_search", {"query": "x"},
            json.dumps({"tool": "web_search", "args": {"query": "x"}}),
            resolve_tools=resolve, emit=lambda e: None,
            tool_timeout_s=5, tool_trace=[], convo=[{"role": "user", "content": "hi"}],
            conversation_id="evolution-eval")
    finally:
        tl.resolve_executor = orig
    assert out.get("ok") is True


async def test_dispatch_defaults_to_hermetic_for_eval_sentinel(monkeypatch):
    """An eval-sentinel conversation_id with no explicit replay flag routes to the
    SEALED path (_dispatch_replay), not the live branch."""
    from server.orchestrator import dispatcher

    seen = {}

    async def fake_dispatch_replay(conversation_id, **kw):
        seen["sealed"] = True
        return {"run_id": 1, "full_output": "ok"}

    async def fake_load_spawn(sid):
        return object()  # non-None; _dispatch_replay is faked so the object is unused

    monkeypatch.setattr(dispatcher, "_dispatch_replay", fake_dispatch_replay)
    monkeypatch.setattr(dispatcher, "_load_spawn", fake_load_spawn)

    await dispatcher.dispatch("evolution-eval", spawn_id=1, task_brief="t")
    assert seen.get("sealed") is True


async def test_dispatch_replay_false_under_sentinel_still_sealed(monkeypatch):
    """No opt-out: even an EXPLICIT replay=False under an eval sentinel is sealed (routes
    to _dispatch_replay), because a safety control is no-override."""
    from server.orchestrator import dispatcher

    sealed = {"v": False}

    async def fake_dispatch_replay(conversation_id, **kw):
        sealed["v"] = True
        return {"run_id": 1, "full_output": "ok"}

    async def fake_load_spawn(sid):
        return object()

    monkeypatch.setattr(dispatcher, "_dispatch_replay", fake_dispatch_replay)
    monkeypatch.setattr(dispatcher, "_load_spawn", fake_load_spawn)

    await dispatcher.dispatch("evolution-eval", spawn_id=1, task_brief="t", replay=False)
    assert sealed["v"] is True  # replay=False did NOT open a live dispatch under the sentinel


async def test_dispatch_real_conversation_stays_live(monkeypatch):
    """A real conversation id with no replay flag does NOT route to the sealed path."""
    from server.orchestrator import dispatcher

    sealed = {"v": False}

    async def fake_dispatch_replay(conversation_id, **kw):
        sealed["v"] = True
        return {"run_id": 1, "full_output": "ok"}

    async def fake_load_spawn(sid):
        return object()

    async def fake_build(*a, **k):
        raise RuntimeError("LIVE_BRANCH_TAKEN")

    monkeypatch.setattr(dispatcher, "_dispatch_replay", fake_dispatch_replay)
    monkeypatch.setattr(dispatcher, "_load_spawn", fake_load_spawn)
    monkeypatch.setattr(dispatcher, "build_spawn_system", fake_build)

    with pytest.raises(RuntimeError, match="LIVE_BRANCH_TAKEN"):
        await dispatcher.dispatch("conv_realuser", spawn_id=1, task_brief="t")
    assert sealed["v"] is False  # real conversation stayed on the live branch


async def test_evaluate_dispatches_hermetically_and_shares_one_ambient(monkeypatch):
    """evaluate routes every candidate dispatch through run_arm with ONE shared ambient
    snapshot (byte-identical arms), never a bare live dispatch."""
    from server.services import evaluator, replay_run

    snapshots = {"count": 0}
    arm_calls = []

    async def fake_snapshot(db, *, spawn_id, conversation_id, task=""):
        snapshots["count"] += 1
        return {"facts": "F", "kb_block": "K", "kb_sources": None}

    async def fake_run_arm(db, *, spawn_id, task, system_prompt, ambient,
                           conversation_id=replay_run.REPLAY_CONVERSATION_ID):
        arm_calls.append({"ambient": ambient, "task": task})
        return {"run_id": len(arm_calls), "output": "cand-out", "evidence": {}}

    monkeypatch.setattr(replay_run, "snapshot_ambient", fake_snapshot)
    monkeypatch.setattr(replay_run, "run_arm", fake_run_arm)

    async def fake_scorer(*, task, persona, output_a, output_b, item):
        return {"dimensions": {}, "overall": "b", "margin": 1.0}

    items = [{"run_id": 1, "task": "t1", "baseline_output": "b1"},
             {"run_id": 2, "task": "t2", "baseline_output": "b2"}]
    res = await evaluator.evaluate(spawn_id=1, persona="p", candidate_prompt="CAND",
                                   replay_items=items, scorer=fake_scorer)
    assert len(arm_calls) == 2                       # both items via run_arm
    assert snapshots["count"] == 1                   # ONE shared ambient for the eval
    assert all(a["ambient"] == {"facts": "F", "kb_block": "K", "kb_sources": None}
               for a in arm_calls)                   # byte-identical ambient
    assert res["gate"]["passed"] is True


def test_scheduled_and_real_conversation_ids_are_not_hermetic():
    """Guard against over-sealing — the biggest adjacent mis-seal surface is the S3-M4
    scheduler, which mints conversation ids as f"scheduled-{task_id}" (scheduler.py:330,480,
    confirmed by grep — NOT "scheduled-task-{id}"). Those LOOK sentinel-ish but are REAL work
    dispatched via `_fire`/`_dispatch_recorded` and MUST run real tools. Pin the exact format
    plus a near-miss variant and a real user id as non-hermetic."""
    from server.services import replay_safety
    # Exact scheduler format (scheduler.py:330,480) + a couple ids — all must be live:
    assert replay_safety.is_hermetic_context("scheduled-42") is False
    assert replay_safety.is_hermetic_context("scheduled-task-42") is False
    assert replay_safety.is_hermetic_context("conv_realuser") is False
    assert replay_safety.is_hermetic_context("") is False


# ── Task 6: regression guard — end-to-end + the throat's run_python escape-valve gap ───────
async def test_evolution_eval_never_exposes_mcp_tool_end_to_end(monkeypatch):
    """End-to-end: an eval dispatch for a spawn wired with an MCP tool must narrow the
    model's toolset to the replay-safe subset (MCP absent) AND, if the model somehow
    calls it, the throat refuses execution (proven separately by the throat tests above).
    This test asserts the seal at the build_spawn_system layer, exactly as it happens on
    a real dispatch — no mocking of dispatcher internals.

    Seeding: reused verbatim from tests/server/test_hermetic_replay.py's `seeded` fixture +
    test_replay_no_mcp_tools (the existing convention in this suite for "a spawn wired with
    an MCP tool") — seed_registry() for the universal safe/wired builtins (web_search,
    web_extract, render_chart), then a hand-added MCPServer/Toolset/Tool row for the MCP
    tool plus a Spawn equipped with that toolset via SpawnCapability(kind="toolset").
    """
    from server.db.models import MCPServer, Spawn, SpawnCapability, Tool, Toolset
    from server.orchestrator import dispatcher
    from server.registry.seeder import seed_registry

    captured = {"wired_keys": None}

    # Spy on build_spawn_system to capture what the model would SEE.
    orig_build = dispatcher.build_spawn_system

    async def spy_build(spawn, **kw):
        system, wired = await orig_build(spawn, **kw)
        captured["wired_keys"] = {t.get("key") for t in wired}
        return system, wired

    monkeypatch.setattr(dispatcher, "build_spawn_system", spy_build)

    # Minimal real spawn wired with an MCP tool (+ the universal web_search from
    # seed_registry), same pattern as test_hermetic_replay.py::test_replay_no_mcp_tools.
    await seed_registry()
    async with db_session.AsyncSessionLocal() as s:
        s.add(MCPServer(id=1, label="msg", command="x", args=[], env=None, status="connected"))
        s.add(Toolset(key="mcp_1", name="msg", description="d", tier="safe", status="wired"))
        s.add(Tool(key="mcp_1__send_message", toolset_key="mcp_1", description="send a message",
                   tier="safe", status="wired", input_schema={}, external_name="send_message"))
        spawn = Spawn(name="EvalTarget", domain_category="x", system_prompt="BASE")
        s.add(spawn)
        await s.flush()
        sid = spawn.id
        s.add(SpawnCapability(spawn_id=sid, kind="toolset", ref_key="mcp_1"))
        await s.commit()

    # Deterministic adapter stub — answers immediately with no tool calls (same
    # content/tool_calls shape as test_hermetic_replay.py's _NativeAdapter/_LLMResp).
    class _LLMResp:
        def __init__(self, content):
            self.content = content
            self.tool_calls = []

    class _NativeAdapter:
        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            return _LLMResp("done")

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _NativeAdapter())

    # Dispatch under the eval sentinel with NO explicit replay — relies on Task 3's
    # structural default (dispatcher.dispatch: `if replay or is_hermetic_context(...)`).
    await dispatcher.dispatch("evolution-eval", spawn_id=sid, task_brief="do it")

    assert captured["wired_keys"] is not None
    assert "mcp_1__send_message" not in captured["wired_keys"]   # filtered from the menu
    assert captured["wired_keys"] <= replay_safety.REPLAY_SAFE_BUILTINS


async def test_throat_refuses_run_python_when_unsandboxed_escape_valve_set(monkeypatch):
    """Task 2 review gap: the throat's run_python-specific branch (tool_loop.py:344-351)
    was untested — run_python IS replay-safe in general (it's in REPLAY_SAFE_BUILTINS), but
    when the unsandboxed escape valve (ARSLAN_ALLOW_UNSANDBOXED_PY) is set it becomes
    networked and therefore NOT hermetic, so the throat must refuse it too even though it
    passes the plain is_replay_safe() check. Mirrors the structure of
    test_throat_refuses_nonsafe_tool_in_hermetic_context_even_if_resolver_leaks /
    test_throat_allows_safe_tool_in_hermetic_context above (manual resolve_executor
    swap-and-restore + an executed[] spy)."""
    monkeypatch.setenv("ARSLAN_ALLOW_UNSANDBOXED_PY", "1")

    executed = []

    async def resolve():
        return [{"key": "run_python"}]

    orig = tool_loop.resolve_executor

    async def fake_resolve_executor(key):
        executed.append(key)
        class _E:
            async def execute(self, args):
                executed.append(("EXECUTED", key))
                return {"ok": True}
        return _E()

    tool_loop.resolve_executor = fake_resolve_executor
    try:
        out = await tool_loop._dispatch_tool(
            "run_python", {"code": "print(1)"},
            json.dumps({"tool": "run_python", "args": {"code": "print(1)"}}),
            resolve_tools=resolve, emit=lambda e: None,
            tool_timeout_s=5, tool_trace=[], convo=[{"role": "user", "content": "hi"}],
            conversation_id="evolution-eval")
    finally:
        tool_loop.resolve_executor = orig

    assert out["ok"] is False
    err = (out.get("error") or "").lower()
    assert "escape valve" in err or "not hermetic" in err
    assert executed == []  # resolve_executor was never even reached, let alone executed
