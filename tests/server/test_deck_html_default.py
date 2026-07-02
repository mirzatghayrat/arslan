"""deck-authoring seed skill: the default presentation deliverable is a designed
single-file HTML deck (raw-document rendering contract, Ember tokens, print-to-PDF),
with render_deck (.pptx) reserved for explicit editable-PowerPoint asks. The skill
seeds with a real body, is assignable, and the deck-capable default spawns carry it."""
import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.registry.seeder as seeder
from server.db.models import Base, SkillPack
from server.registry.service import skill_is_assignable
from server.services.default_spawns import DEFAULT_SPAWNS


def _seeded_row(tmp_path) -> SkillPack:
    """Seed the real catalog (real seeds dir, no monkeypatch) into a scratch DB."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as db:
            await seeder.seed_registry_with(db)
        async with m() as db:
            return (await db.execute(
                select(SkillPack).where(SkillPack.key == "deck-authoring"))).scalar_one()
    return anyio.run(_run)


def test_seeds_with_html_default_body_and_is_assignable(tmp_path):
    row = _seeded_row(tmp_path)
    body = row.body or ""
    # Raw-document rendering contract: the reply must BE the HTML document (no fences),
    # which is what makes the client show the preview/download card.
    assert "<!DOCTYPE html" in body
    # pptx stays as the explicit-ask path via the render_deck tool.
    assert "render_deck" in body
    # Ember design tokens verbatim + on-dark accent variant.
    assert "#D94420" in body and "#F06A20" in body and "#F2EBE0" in body
    # Print contract: one slide per page so print-to-PDF works.
    assert "@media print" in body
    # Project design spec overrides the default tokens.
    assert "design.md" in body
    assert skill_is_assignable(row.tier, row.status, body)


def test_deck_capable_defaults_equip_it():
    by_name = {s["name"]: s for s in DEFAULT_SPAWNS}
    for name in ("Deck Master", "Financial Research Analyst"):
        assert "deck-authoring" in by_name[name]["equipment"]["skills"], name
        # render_deck stays wired for explicit .pptx asks.
        assert "deck" in by_name[name]["equipment"]["toolsets"], name


def test_deck_master_persona_defaults_to_html():
    dm = next(s for s in DEFAULT_SPAWNS if s["name"] == "Deck Master")
    role = dm["persona_role"]
    # Identity says HTML-by-default, pptx-on-request — not "always ships .pptx".
    assert "HTML" in role
    assert "render_deck" in role
    assert "default" in role
