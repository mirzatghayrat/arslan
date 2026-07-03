"""Idempotent registry seeding: insert-or-update by key; deletes ONLY explicitly
retired seed keys (never user-created rows — MCP toolsets use mcp_* keys and
imported/promoted skills carry their own keys, none of which appear in the
retirement lists; the literal key match IS the safety)."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import arslan.spawn
from arslan.spawn.skillpack import SkillPack as _SkillPackSpec
from server.db import session as db_session
from server.db.models import SkillPack, Tool, Toolset
from server.registry.seed_catalog import SKILLS, TOOLSETS

logger = logging.getLogger(__name__)

_SEEDS_DIR = Path(arslan.spawn.__file__).parent / "seeds"

# ── Retirement lists (2026-07 open-source curation) ────────────────────────────
# Seed keys that used to ship in the catalog and must be removed from existing
# DBs on boot. ONLY keys listed here are ever deleted; the seeder never deletes
# anything else. Keep entries forever (deletion is idempotent on absent keys).
RETIRED_SKILL_KEYS: tuple[str, ...] = (
    # integration placeholders (no method body; the integration never existed)
    "apple-notes", "apple-reminders", "findmy", "imessage", "himalaya",
    "airtable", "google-workspace", "maps", "notion", "nano-pdf", "obsidian",
    "xurl", "gif-search", "polymarket", "manim-video", "ascii-video",
    "audiocraft-audio-generation", "huggingface-hub", "segment-anything-model",
    "weights-and-biases", "llama-cpp", "serving-llms-vllm",
    "evaluating-llms-harness", "openhue", "comfyui", "jupyter-live-kernel",
    # unclear / redundant / infeasible
    "dogfood", "heartmula", "songsee", "popular-web-designs", "powerpoint",
    "ocr-and-documents", "codebase-inspection", "yuanbao-groups",
    "macos-computer-use", "teams-meeting-pipeline", "touchdesigner-mcp",
)
RETIRED_TOOLSET_KEYS: tuple[str, ...] = (
    "discord", "discord_admin", "spotify", "x_search", "home_assistant",
    "cross_platform_messaging", "image_generation", "video_generation",
    "video_analysis", "vision_analysis", "text_to_speech", "code_execution",
    "mixture_of_agents", "task_delegation", "memory", "clarifying_questions",
    "browser_automation", "terminal_processes", "cron_jobs", "computer_use",
    "context_engine", "yuanbao",
)


def _skill_body(key: str) -> str | None:
    """Read the SKILL.md body for a seeded skill key, or None if absent/unparseable.
    Catalog tuple stays authoritative for metadata; the file provides ONLY the body."""
    md = _SEEDS_DIR / key / "SKILL.md"
    if not md.exists():
        return None
    try:
        return _SkillPackSpec.from_skill_md(md.read_text(encoding="utf-8")).body or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("seed skill body parse failed for %s: %s", key, exc)
        return None


async def _retire_removed_seeds(db: AsyncSession) -> None:
    """Delete retired seed rows (and the retired toolsets' tools). Idempotent;
    touches ONLY the literal keys above — user rows (mcp_* toolsets, imported
    or promoted skills) are never in these lists."""
    await db.execute(delete(Tool).where(Tool.toolset_key.in_(RETIRED_TOOLSET_KEYS)))
    await db.execute(delete(Toolset).where(Toolset.key.in_(RETIRED_TOOLSET_KEYS)))
    await db.execute(delete(SkillPack).where(SkillPack.key.in_(RETIRED_SKILL_KEYS)))


async def seed_registry_with(db: AsyncSession) -> None:
    """Upsert the full catalog into the given session. Reclassifications ship as
    code changes and are applied on restart; rows are deleted ONLY via the
    explicit retirement lists (user grants may reference everything else)."""
    await _retire_removed_seeds(db)
    for ts in TOOLSETS:
        row = await db.get(Toolset, ts["key"])
        if row is None:
            row = Toolset(key=ts["key"])
            db.add(row)
        row.name = ts["name"]
        row.description = ts["description"]
        row.tier = ts["tier"]
        row.status = ts["status"]
        row.backend_note = ts.get("backend_note")
        for tkey, tdesc, ttier, tstatus in ts.get("tools", []):
            trow = await db.get(Tool, tkey)
            if trow is None:
                trow = Tool(key=tkey, toolset_key=ts["key"])
                db.add(trow)
            trow.toolset_key = ts["key"]
            trow.description = tdesc
            trow.tier = ttier
            trow.status = tstatus
    for key, name, category, description, tier, status in SKILLS:
        srow = await db.get(SkillPack, key)
        if srow is None:
            srow = SkillPack(key=key)
            db.add(srow)
        srow.name = name
        srow.category = category
        srow.description = description
        srow.tier = tier
        srow.status = status
        srow.body = _skill_body(key)
    await db.commit()


async def seed_registry() -> None:
    """Upsert the full catalog using the app's default session factory."""
    async with db_session.AsyncSessionLocal() as db:
        await seed_registry_with(db)
