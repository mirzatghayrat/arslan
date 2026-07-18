"""brain-P2 Task 6: token cost of recall/remember, measured at the two places
they actually cost tokens — mirrors the suggest_connect_mcp <120-tok precedent
(tests/server/test_router_connect_mcp.py, measured 54 tok) and the "54-tok
discipline" anchor named in the P2 spec
(docs/superpowers/specs/2026-07-18-brain-p2-agentic-memory-design.md:21).

Token cost reality (spec §Token 成本实情, and verified directly against
arslan/llm/providers/anthropic_provider.py:114-115): Arslan's Anthropic path is
intentionally text-in/text-out — `tools` is NEVER serialized into the Anthropic
request, so the recall/remember JSON parameter schema (_NATIVE_PARAM_SCHEMAS)
costs the Claude backend exactly ZERO tokens. The token cost that is ALWAYS
paid, on every backend, is the two tools' DESCRIPTION TEXT:

  (a) host path — arslan.py:_arslan_tools()'s live `desc` dict entries for
      "recall"/"remember". This text becomes each OpenAI-style function
      schema's `description` field (tool_loop._native_tool_schemas), paid by
      native-tool-calling providers (e.g. DeepSeek) on every turn.
  (b) spawn path — dispatcher.py:_equipment_block_from()'s rendered
      "- TOOL <key> (live): <description>" lines, injected as PROSE into every
      equipped spawn's system prompt, on EVERY provider (host and spawn both
      route through tool_loop.run_native, but only the spawn path also pays a
      prose cost independent of native tool-calling support).

Both measurements below pull the live description strings from their real
source (arslan._arslan_tools() / seed_catalog.TOOLSETS via the real
dispatcher._equipment_block_from renderer) — never copy-pasted literals — so a
future edit that bloats either description fails this test immediately
(regression / anti-drift, same discipline as the suggest_connect_mcp precedent).

Measured 2026-07-18 (recorded here for the reviewer, per the suggest_connect_mcp
precedent's comment style):
  host   recall=23 tok, remember=21 tok, combined=44 tok
  spawn  recall-line=30 tok, remember-line=52 tok, combined=82 tok
  host + spawn combined = 126 tok < 200 tok target (plan Task 6 decision point).

(Informational only, NOT part of the pinned bound: the full OpenAI function
schema for host — description + JSON parameters — measures ~207 tok combined.
That is real cost for native-tool-calling providers, but it is mechanical
schema overhead shared by every tool's parameter shape (enum members, property
names), not discretionary prose bloat, so it is not what the 54-tok discipline
targets — see the spec quote above.)
"""
from __future__ import annotations

from server.orchestrator.memory import estimate_tokens


async def _host_descriptions(monkeypatch) -> tuple[str, str]:
    """Live recall/remember description strings from arslan._arslan_tools(),
    exactly as they flow into the native tool-calling schema's `description`
    field. Needs a throwaway DB (the function queries Tool/settings for the
    optional shell/MCP tools, which we don't care about here)."""
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
    by_key = {t["key"]: t for t in tools}
    return by_key["recall"]["description"], by_key["remember"]["description"]


def _spawn_equipment_lines() -> tuple[str, str]:
    """Live "- TOOL <key> (live): <description>" lines exactly as
    dispatcher._equipment_block_from renders them for a spawn equipped with
    ONLY second_brain — sourced from the real seed_catalog.TOOLSETS entry (the
    catalog that seeds the Tool rows _equipment_block_from's caller queries),
    not a copy-pasted string."""
    from server.orchestrator.dispatcher import _equipment_block_from
    from server.registry.seed_catalog import TOOLSETS

    second_brain = next(ts for ts in TOOLSETS if ts["key"] == "second_brain")
    desc_by_key = {t[0]: t[1] for t in second_brain["tools"]}
    wired = [
        {"key": "recall", "description": desc_by_key["recall"]},
        {"key": "remember", "description": desc_by_key["remember"]},
    ]
    block = _equipment_block_from({"toolsets": [], "skills": []}, wired)
    tool_lines = [ln for ln in block.splitlines() if ln.startswith("- TOOL ")]
    recall_line = next(ln for ln in tool_lines if ln.startswith("- TOOL recall "))
    remember_line = next(ln for ln in tool_lines if ln.startswith("- TOOL remember "))
    return recall_line, remember_line


# ---------------------------------------------------------------------------
# (a) host path — arslan._arslan_tools() description strings
# ---------------------------------------------------------------------------

async def test_host_recall_remember_description_tokens_bounded(monkeypatch):
    recall_desc, remember_desc = await _host_descriptions(monkeypatch)
    recall_tok = estimate_tokens(recall_desc)
    remember_tok = estimate_tokens(remember_desc)
    combined = recall_tok + remember_tok

    assert recall_tok < 50, f"host recall description grew to {recall_tok} tok: {recall_desc!r}"
    assert remember_tok < 50, f"host remember description grew to {remember_tok} tok: {remember_desc!r}"
    assert combined < 90, f"host recall+remember combined grew to {combined} tok"


# ---------------------------------------------------------------------------
# (b) spawn path — dispatcher._equipment_block_from rendered lines
# ---------------------------------------------------------------------------

def test_spawn_equipment_block_recall_remember_tokens_bounded():
    recall_line, remember_line = _spawn_equipment_lines()
    recall_tok = estimate_tokens(recall_line)
    remember_tok = estimate_tokens(remember_line)
    combined = recall_tok + remember_tok

    assert recall_tok < 60, f"spawn recall line grew to {recall_tok} tok: {recall_line!r}"
    assert remember_tok < 100, f"spawn remember line grew to {remember_tok} tok: {remember_line!r}"
    assert combined < 150, f"spawn recall+remember combined grew to {combined} tok"


# ---------------------------------------------------------------------------
# combined — the plan's actual decision-point target (< 200 tok)
# ---------------------------------------------------------------------------

async def test_host_plus_spawn_combined_under_200_tokens(monkeypatch):
    """The plan's Task 6 decision-point target: host-path + spawn-path combined
    token cost of recall+remember stays under 200 tok. Measured 2026-07-18:
    44 (host) + 82 (spawn) = 126 tok — comfortably under target, no fudging
    needed. If a future edit pushes this over 200, that is a real regression:
    either shrink the description or explicitly re-budget with a comment here."""
    recall_desc, remember_desc = await _host_descriptions(monkeypatch)
    host_combined = estimate_tokens(recall_desc) + estimate_tokens(remember_desc)

    recall_line, remember_line = _spawn_equipment_lines()
    spawn_combined = estimate_tokens(recall_line) + estimate_tokens(remember_line)

    total = host_combined + spawn_combined
    assert total < 200, f"host+spawn recall+remember token cost grew to {total} tok (target < 200)"
