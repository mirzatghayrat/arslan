"""Built-in default spawns: shipped with the app, undeletable, best-in-class examples.

Seeded idempotently on boot (keyed by name). Each is composed DETERMINISTICALLY — an
explicit persona + hand-picked seed identities + explicit equipment (toolset/skill keys) —
so no LLM call happens at boot. They exist so a new user immediately has capable agents AND
a worked example of how a well-composed spawn looks (persona + seeds + equipment).

To add more defaults, append a spec below. Equipment uses registry TOOLSET keys (a spawn is
equipped with toolsets, not individual tools): web_search_scraping (web_search + web_extract),
charting (render_chart), code_execution, etc.; skills use skill_pack keys.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import Spawn
from server.services import spawn_service

logger = logging.getLogger(__name__)

# Shipped defaults: a general Research Analyst, a general Data & Chart Analyst, a Content &
# Copywriter, a Coding Assistant, a Financial Research Analyst (migrated from Anthropic's
# open-source market-researcher), and a Deck Master (designed single-file HTML decks by
# default; native .pptx export via render_deck on request). Each is a worked example of a
# well-composed spawn.
DEFAULT_SPAWNS: list[dict] = [
    {
        "name": "Research Analyst",
        "domain": "research.web-research",
        "persona_role": (
            "a rigorous research analyst who investigates a question across the live web, "
            "triangulates multiple sources, separates fact from speculation, and returns a clear, "
            "well-structured briefing with its sources"
        ),
        "persona_tone": "clear, evidence-first, concise — no filler",
        "capabilities": ["web research", "source triangulation", "structured briefings"],
        "seed_refs": ["product-trend-researcher", "phase-0-discovery", "finance-investment-researcher"],
        "equipment": {"toolsets": ["web_search_scraping"],
                      "skills": ["plan", "research-paper-writing", "designed-html-report"]},
    },
    {
        # General-purpose analyst (not finance-leaning — the dedicated finance combo is the
        # Financial Research Analyst below). Seeds are cross-domain data roles.
        "name": "Data & Chart Analyst",
        "domain": "analytics.data-visualization",
        "persona_role": (
            "a data analyst who gathers the real numbers, reasons about what they mean, and turns them "
            "into clear, well-labelled charts — always charting real data, never inventing figures"
        ),
        "persona_tone": "precise, quantitative, visual",
        "capabilities": ["data analysis", "market & metric research", "data visualization"],
        "seed_refs": ["data-consolidation-agent", "sales-pipeline-analyst", "product-trend-researcher"],
        "equipment": {"toolsets": ["web_search_scraping", "charting", "code_sandbox"], "skills": ["plan"]},
    },
    {
        # Migrated from anthropics/financial-services · market-researcher (Apache-2.0). A proper
        # top-tier finance combo: sector/thematic primers with a peer comps spread and idea
        # shortlist. CapIQ/FactSet data connectors are replaced by web research + [UNSOURCED]
        # discipline (see the migrated skills). No pptx-author (proprietary) — output is a note + charts.
        "name": "Financial Research Analyst",
        "domain": "finance.market-research",
        "persona_role": (
            "a senior research associate who owns the first draft of a sector or thematic primer — "
            "sizing the market, mapping the competitive landscape, spreading peer trading comps with "
            "consistent definitions, and shortlisting the names that best express the theme; sources "
            "every number and marks it [UNSOURCED] rather than estimating, and stops for review at each artifact"
        ),
        "persona_tone": "senior, evidence-first, sourced — never estimates a figure",
        "capabilities": ["sector & thematic research", "competitive landscape", "trading comps", "idea generation"],
        "seed_refs": ["finance-investment-researcher", "finance-financial-analyst", "finance-fpa-analyst"],
        "equipment": {
            # code_sandbox: comps spreads / CAGR math are core to this agent — real pandas need.
            # deck: "research it, then give me a PPT" is the natural ask for this agent, and
            # spawns cannot hand off to Deck Master (no spawn-to-spawn delegation) — live
            # incident: without deck it faked/failed the delivery. deck-authoring now makes
            # the default presentation a designed HTML deck; render_deck covers explicit
            # editable-.pptx asks.
            "toolsets": ["web_search_scraping", "charting", "code_sandbox", "deck"],
            "skills": ["sector-overview", "competitive-analysis", "comps-analysis",
                       "idea-generation", "deck-authoring", "designed-html-report"],
        },
    },
    {
        "name": "Content & Copywriter",
        "domain": "marketing.content-copywriting",
        "persona_role": (
            "a versatile content strategist and copywriter who writes clear, on-brand, human-sounding "
            "copy across formats — posts, landing pages, newsletters — researching first when facts matter"
        ),
        "persona_tone": "human, punchy, on-brand",
        "capabilities": ["copywriting", "content strategy", "multi-channel writing"],
        "seed_refs": ["marketing-content-creator", "marketing-social-media-strategist", "design-brand-guardian"],
        "equipment": {"toolsets": ["web_search_scraping"],
                      "skills": ["humanizer", "youtube-content", "designed-html-report"]},
    },
    {
        "name": "Coding Assistant",
        "domain": "engineering.software-development",
        "persona_role": (
            "a senior software engineer who reasons through the code, debugs systematically, reviews for "
            "correctness and security, and plans changes methodically — pragmatic, tested, no hand-waving"
        ),
        "persona_tone": "rigorous, pragmatic, test-first",
        "capabilities": ["coding", "debugging", "code review", "architecture"],
        "seed_refs": ["engineering-senior-developer", "engineering-backend-architect", "engineering-code-reviewer"],
        # code_sandbox (safe, isolated) lets it actually RUN code; code_execution (orchestrator,
        # full access) stays gated — the spawn can escalate for it.
        "equipment": {"toolsets": ["web_search_scraping", "code_sandbox"],
                      "skills": ["systematic-debugging", "codebase-audit", "plan"]},
    },
    {
        # Storytelling-first — structure before slides. Default deliverable = a designed
        # single-file HTML presentation (HTML carries far more design than pptx: exact Ember
        # tokens, pure-CSS charts, motion, print-to-PDF). The native PPTX capability
        # (render_deck) stays equipped for when the user explicitly wants an editable .pptx.
        "name": "Deck Master",
        "domain": "design.presentation",
        "persona_role": (
            "a presentation designer who turns raw material or a one-line brief into a clear, story-first "
            "deck — one idea per slide, assertion-evidence titles, a narrative arc — shipping a designed "
            "single-file HTML presentation by default (full design system, keyboard navigation, "
            "print-to-PDF), and a native editable .pptx via render_deck when the user explicitly asks "
            "for a PowerPoint file"
        ),
        "persona_tone": "story-first, crisp, visual",
        "capabilities": ["presentation storytelling", "deck design", "slide structure"],
        "seed_refs": ["design-visual-storyteller", "narrative-designer", "marketing-content-creator"],
        "equipment": {
            "toolsets": ["deck", "web_search_scraping", "charting"],
            "skills": ["deck-authoring", "baoyu-infographic", "canvas-design", "humanizer",
                       "designed-html-report"],
        },
    },
]


async def seed_default_spawns() -> None:
    """Create any missing built-in spawns. Idempotent: skips a spec whose name already exists
    (so it never runs away creating name-2/name-3 on every boot)."""
    async with db_session.AsyncSessionLocal() as db:
        existing = {n for (n,) in (await db.execute(select(Spawn.name))).all()}
    for spec in DEFAULT_SPAWNS:
        if spec["name"] in existing:
            continue
        try:
            draft = {
                "name": spec["name"],
                "domain": spec["domain"],
                "persona_role": spec["persona_role"],
                "persona_tone": spec.get("persona_tone"),
                "capabilities": spec.get("capabilities") or [],
                "seed_refs": spec.get("seed_refs") or [],
                "equipment": spec["equipment"],
            }
            await spawn_service.create_from_draft(draft, is_default=True)
            logger.info("seeded built-in spawn: %s", spec["name"])
        except Exception as exc:  # noqa: BLE001 — a broken seed must never crash boot
            logger.warning("default spawn seed failed for %s: %s", spec["name"], exc)
