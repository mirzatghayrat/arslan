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
# 1. (Removed in v0.1.64 CAP1a, with the rest of the discovery centre; kept as the record.)
#    server/api/discovery.py:33-34 `POST /discovery/evaluate` → discovery_service.evaluate_ref
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
# :480, used by `_fire` for REAL work — since 0.1.63 (C1) an Arslan turn, before that a
# `dispatcher.dispatch` of the task's spawn)
# — i.e. "scheduled-42", NOT "scheduled-task-42". `test_scheduled_and_real_conversation_ids_
# are_not_hermetic` below pins the REAL format plus a near-miss variant, a real user id, and
# empty string as all non-hermetic.
import json

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base
from server.services import replay_safety
from server.orchestrator import tool_loop

# The replay sentinel replay_safety still seals (replay_run, which defined it, went in C7b-2).
REPLAY_CONVERSATION_ID = "evolution-replay"


@pytest_asyncio.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    """Autouse, file-scoped DB isolation: every test here gets its own schema-created
    SQLite behind db_session.AsyncSessionLocal, so nothing reaches whatever real DB
    ARSLAN_DATA_DIR resolves to. (The dispatch tests that first needed it went with the
    dispatcher in C7b-4; the isolation stays for the rest.)
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


def test_every_sentinel_in_product_code_is_sealed():
    """Census, not a tautology over the set's own literals.

    Every `evolution-*` conversation-id literal anywhere in server/ or arslan/ (outside
    replay_safety, which DEFINES the set) must be a member of the hermetic set, and every
    member must stay hermetic AND non-curatable. A new eval/replay entry point that
    dispatches under a fresh sentinel without adding it to the set fails here.

    Rewritten in C7b-2 (v0.1.63): the old version read the sentinel from
    replay_run.REPLAY_CONVERSATION_ID, which went with replay_run. Kept after the
    dispatcher went (C7b-4): tool_loop still seals on is_hermetic_context, so a new
    unsealed sentinel would still matter. Goes with replay_safety (card step 3, v0.1.64).
    """
    import ast
    import pathlib
    import re

    root = pathlib.Path(replay_safety.__file__).resolve().parents[2]
    sentinel = re.compile(r"^evolution-[a-z][a-z-]*$")
    found: dict[str, list[str]] = {}
    for top in ("server", "arslan"):
        for path in (root / top).rglob("*.py"):
            if path.name == "replay_safety.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and sentinel.match(node.value):
                    found.setdefault(node.value, []).append(f"{path.relative_to(root)}:{node.lineno}")
    unsealed = {s: where for s, where in found.items() if s not in replay_safety._HERMETIC_CONVERSATION_IDS}
    assert not unsealed, f"sentinel conversation ids outside the hermetic set: {unsealed}"

    assert replay_safety._HERMETIC_CONVERSATION_IDS          # the census has something to hold
    for s in replay_safety._HERMETIC_CONVERSATION_IDS:
        assert replay_safety.is_hermetic_context(s) is True


# --------------------------------------------------------------------------- the hermetic set stays narrow


def test_only_eval_sentinels_are_hermetic():
    """🔴 is_hermetic_context makes tool_loop's throat refuse every non-replay-safe tool.
    A real, scheduled or background conversation id in the hermetic set would seal that
    work's own writes; this test is the tripwire. (Its sibling predicate,
    should_not_curate, went with distill_service in C8-4, v0.1.63.)"""
    for cid in replay_safety._HERMETIC_CONVERSATION_IDS:
        assert cid.startswith("evolution-"), (
            "only evolution eval/replay sentinels may be hermetic — a real or background "
            "id here would make tool_loop refuse that work's own writes")
    assert replay_safety.is_hermetic_context("conv_abc123") is False
    assert replay_safety.is_hermetic_context("scheduled-7") is False   # real work
    assert replay_safety.is_hermetic_context(None) is False


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


def test_scheduled_and_real_conversation_ids_are_not_hermetic():
    """Guard against over-sealing — the biggest adjacent mis-seal surface is the S3-M4
    scheduler, which mints conversation ids as f"scheduled-{task_id}" (scheduler.py:330,480,
    confirmed by grep — NOT "scheduled-task-{id}"). Those LOOK sentinel-ish but are REAL work
    run via `_fire` (an Arslan turn since 0.1.63) and MUST run real tools. Pin the exact format
    plus a near-miss variant and a real user id as non-hermetic."""
    from server.services import replay_safety
    # Exact scheduler format (scheduler.py:330,480) + a couple ids — all must be live:
    assert replay_safety.is_hermetic_context("scheduled-42") is False
    assert replay_safety.is_hermetic_context("scheduled-task-42") is False
    assert replay_safety.is_hermetic_context("conv_realuser") is False
    assert replay_safety.is_hermetic_context("") is False


# ── Task 6: regression guard — end-to-end + the throat's run_python escape-valve gap ───────
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
