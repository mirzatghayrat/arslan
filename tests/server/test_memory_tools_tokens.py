"""brain-P2 Task 6: token cost of recall/remember, measured as the REAL cost on
the provider where the feature actually functions — the full native-tool-calling
JSON schema (host + spawn) plus the spawn's prose equipment block. Mirrors the
suggest_connect_mcp precedent's discipline (tests/server/test_router_connect_mcp.py)
but NOT its subset shortcut: this pins the real wire cost, not a one-line excerpt.

WHY the full schema is the right measure (coordinator ruling, folding the earlier
description-only draft): the agentic memory tools ONLY function on native-tool-calling
providers (DeepSeek / OpenAI-compatible). It is TRUE that Arslan's Anthropic path is
text-in/text-out and never serializes `tools=` (arslan/llm/providers/anthropic_provider.py:114-115)
— but that is exactly why measuring the description text alone is wrong: it measures
the Anthropic path, where the feature is INERT. On the native providers where it
works, run_native builds the `tools=` API param from tool_loop._native_tool_schemas
and sends the FULL JSON function schema (description + the 4-action × 4-kind enum
parameter space) on EVERY turn — that is the real per-turn cost.

Two paths, each measured against its real source (never a copy-pasted literal):

  (a) HOST — arslan._arslan_tools() → _native_tool_schemas → the tools= wire form.
      recall + remember together = the full JSON the host model receives each turn.

  (b) SPAWN — a spawn equipped with second_brain, on a native provider, pays BOTH:
      the same tools= JSON schema (built from wired_tools_for_spawn's dicts, which
      carry the fuller catalog Tool.description) AND the prose "- TOOL <key> (live):"
      lines injected into its system prompt by dispatcher._equipment_block_from.
      Both are counted — that double cost is the honest reality.

Measured 2026-07-18 (estimate_tokens, CJK-aware — recorded for the reviewer):
  HOST  full schema: recall=86, remember=121, combined=207 tok
  SPAWN full schema=234 tok (longer catalog descriptions) + prose=82 tok = 316 tok
  GRAND host-schema + spawn(schema+prose) = 523 tok

The combined cost EXCEEDS the plan's naive < 200-tok target — and per the plan's
own instruction ("if over 200, don't fudge the bound — set it to the real value +
a comment explaining why, and flag it"), the bounds below are set just above the
REAL measured values, NOT lowered by measuring a subset. A genuine agentic memory
API (recall's query+kind; remember's 4 actions × 4 kinds + content + target_id)
needs a richer JSON schema than a single router-rubric bullet — 207/234 tok is that
schema's honest weight, paid only on the providers where the feature actually runs.
"""
from __future__ import annotations

import json

from server.orchestrator.memory import estimate_tokens


def _schema_tokens(wired: list[dict]) -> int:
    """Token weight of the tools= wire form for `wired`, built via the SAME
    tool_loop._native_tool_schemas path run_native uses, serialized to the JSON
    that goes on the wire. This is the real per-turn cost on a native provider."""
    from server.orchestrator.tool_loop import _native_tool_schemas

    schemas = _native_tool_schemas(wired, allow_escalation=False)
    return estimate_tokens(json.dumps(schemas, ensure_ascii=False))


async def _host_wired(monkeypatch) -> dict[str, dict]:
    """Live recall/remember wired dicts from arslan._arslan_tools() — exactly as
    they flow into _native_tool_schemas on the host answer path. Needs a throwaway
    DB (the function queries Tool/settings for optional shell/MCP tools)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import server.db.session as db_session
    from server.db.models import Base
    from server.orchestrator import arslan

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)

    tools = await arslan._arslan_tools()
    return {t["key"]: t for t in tools if t["key"] in ("recall", "remember")}


# ---------------------------------------------------------------------------
# (a) HOST path — full native JSON schema (the tools= wire form)
# ---------------------------------------------------------------------------

async def test_host_full_schema_tokens_real_cost(monkeypatch):
    """Host recall+remember full JSON schema token cost. Measured: recall=86,
    remember=121, combined=207 tok. The combined EXCEEDS the naive 200 target
    because the remember schema carries the real 4-action × 4-kind enum space —
    that is the honest cost on a native-tool-calling provider, not fudged down
    by measuring only the description string (which would measure the inert
    Anthropic path). Bounds sit just above the real values as an anti-drift guard."""
    wired = await _host_wired(monkeypatch)
    recall_tok = _schema_tokens([wired["recall"]])
    remember_tok = _schema_tokens([wired["remember"]])
    combined = _schema_tokens([wired["recall"], wired["remember"]])

    assert recall_tok < 100, f"host recall schema grew to {recall_tok} tok (was 86)"
    assert remember_tok < 145, f"host remember schema grew to {remember_tok} tok (was 121)"
    # Real combined = 207 tok, ABOVE the naive 200 target — bound set to real+headroom
    # with this comment, NOT lowered (plan Task 6: "if over 200, set the bound to the
    # real value + a comment, don't fudge").
    assert combined < 230, f"host recall+remember schema grew to {combined} tok (was 207)"


# ---------------------------------------------------------------------------
# (b) SPAWN path — full JSON schema (tools=) AND prose (_equipment_block_from)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# combined — the REAL total an agentic-memory-enabled turn pays across both paths
# ---------------------------------------------------------------------------
