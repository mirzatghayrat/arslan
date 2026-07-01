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

# The first shipped default. More (Data/Chart Analyst, Content & Copywriter, Coding assistant)
# are added after this one's quality bar is confirmed.
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
        "equipment": {"toolsets": ["web_search_scraping"], "skills": ["plan", "research-paper-writing"]},
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
