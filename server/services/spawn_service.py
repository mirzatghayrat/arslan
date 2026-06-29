"""Spawn persistence and DTO mapping over the database."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete as sa_delete, exists, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import ChatMessage, Spawn
from server.schemas import ChatMessageOut, SpawnDetailOut, SpawnOut


_MAX_CAPABILITIES = 6
_MAX_CAP_LEN = 40


def normalize_capabilities(value: Any) -> list[str]:
    """Coerce an LLM-produced `capabilities` value into a clean string list.

    Models are inconsistent: a draft's capabilities may come back as a JSON array,
    a comma-joined string (incl. the full-width comma '，'), or be missing entirely.
    Downstream consumers (the create-spawn card, the DB column) expect a list, so we
    normalize at the source. We also drop sentence-length junk and cap the count so a
    chatty model can't stuff a whole paragraph into the Trigger line.
    """
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
    elif isinstance(value, str):
        items = [part.strip() for part in re.split(r"[,，]", value) if part.strip()]
    else:
        return []
    items = [c for c in items if len(c) <= _MAX_CAP_LEN]
    return items[:_MAX_CAPABILITIES]


def normalize_draft(draft: Any) -> dict:
    """Return a copy of a suggested-spawn draft with `capabilities` coerced to a list."""
    if not isinstance(draft, dict):
        return {}
    normalized = dict(draft)
    normalized["capabilities"] = normalize_capabilities(draft.get("capabilities"))
    return normalized


_SUFFIX_RE = re.compile(r"^(?P<base>.+)-\d+$")


def _names_overlap(a: str, b: str) -> bool:
    """True iff equal, or one is the other plus a '-<digits>' uniqueness suffix.

    Stripping suffixes from BOTH sides over-matched (top-10 vs top-1); the
    pairwise rule only treats '-N' as a suffix relative to an existing base.
    (plan: Task 6, step 3)
    """
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    ma, mb = _SUFFIX_RE.match(a), _SUFFIX_RE.match(b)
    return bool(ma and ma.group("base") == b) or bool(mb and mb.group("base") == a)


def find_overlap(draft: dict, spawns: list) -> dict | None:
    """Return {spawn_id, name, axes} for an existing spawn that overlaps the draft, else None.

    Overlap fires on (1) pairwise NAME overlap (_names_overlap), or (2) full
    'category.subcategory' domain equality. Coarse domain_category alone NEVER matches
    (finance.equity-research and finance.crypto are distinct). `axes` is left [] here;
    callers may merge the LLM's axes.
    """
    ddomain = (draft.get("domain") or "").strip().lower()
    _dcat, _, dsub = ddomain.partition(".")
    for s in spawns:
        if _names_overlap(draft.get("name") or "", s.name):
            return {"spawn_id": s.id, "name": s.name, "axes": []}
        if dsub and s.domain_subcategory:
            s_full = f"{s.domain_category}.{s.domain_subcategory}".strip().lower()
            if s_full == ddomain:
                return {"spawn_id": s.id, "name": s.name, "axes": []}
    return None


def build_system_prompt(draft: dict) -> str:
    role = draft.get("persona_role") or "a helpful assistant"
    tone = draft.get("persona_tone") or ""
    domain = draft.get("domain") or ""
    parts = [f"You are {role}."]
    if tone:
        parts.append(f"Tone: {tone}.")
    if domain:
        parts.append(f"Domain focus: {domain}.")
    return " ".join(parts)


def _domain(spawn: Spawn) -> str:
    if spawn.domain_subcategory:
        return f"{spawn.domain_category}.{spawn.domain_subcategory}"
    return spawn.domain_category


def to_summary(spawn: Spawn) -> SpawnOut:
    return SpawnOut(
        id=spawn.id,
        name=spawn.name,
        domain=_domain(spawn),
        capabilities=spawn.capabilities or [],
        template_used=spawn.template_used,
        generation_level=spawn.generation_level or 1,
        created_at=spawn.created_at.isoformat() if spawn.created_at else "",
        updated_at=spawn.updated_at.isoformat() if spawn.updated_at else "",
    )


def to_detail(spawn: Spawn, messages: list[ChatMessage]) -> SpawnDetailOut:
    return SpawnDetailOut(
        **to_summary(spawn).model_dump(),
        persona_role=spawn.persona_role,
        persona_tone=spawn.persona_tone,
        system_prompt=spawn.system_prompt or "",
        messages=[
            ChatMessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                timestamp=m.timestamp.isoformat() if m.timestamp else "",
            )
            for m in messages
        ],
    )


async def _has_active_chat(session: AsyncSession, spawn_id: int) -> bool:
    return bool((await session.execute(
        select(exists().where(ChatMessage.spawn_id == spawn_id, ChatMessage.archived == False))  # noqa: E712
    )).scalar())


async def list_spawns(session: AsyncSession) -> list[SpawnOut]:
    result = await session.execute(select(Spawn).order_by(Spawn.created_at))
    rows = result.scalars().all()
    out_list = []
    for s in rows:
        out = to_summary(s)
        out.has_active_chat = await _has_active_chat(session, s.id)
        out_list.append(out)
    return out_list


async def get_spawn(session: AsyncSession, spawn_id: int) -> Spawn | None:
    return await session.get(Spawn, spawn_id)


async def get_detail(session: AsyncSession, spawn_id: int) -> SpawnDetailOut | None:
    spawn = await session.get(Spawn, spawn_id)
    if spawn is None:
        return None
    msgs = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.spawn_id == spawn_id)
        .order_by(ChatMessage.id)
    )
    return to_detail(spawn, list(msgs.scalars().all()))


async def update_config(
    session: AsyncSession,
    spawn_id: int,
    *,
    system_prompt: str | None = None,
    persona_tone: str | None = None,
    persona_role: str | None = None,
    config: dict | None = None,
) -> Spawn | None:
    spawn = await session.get(Spawn, spawn_id)
    if spawn is None:
        return None
    if system_prompt is not None:
        spawn.system_prompt = system_prompt
    if persona_tone is not None:
        spawn.persona_tone = persona_tone
    if persona_role is not None:
        spawn.persona_role = persona_role
    if config is not None:
        spawn.config = config
    await session.commit()
    await session.refresh(spawn)
    return spawn


async def delete_spawn(session: AsyncSession, spawn_id: int) -> bool:
    spawn = await session.get(Spawn, spawn_id)
    if spawn is None:
        return False
    # Deterministic cleanup, independent of SQLite FK pragma state:
    # the orchestrator thread keeps its rows (display history) but unlinks them;
    # spawn-scoped rows go with the spawn.
    from server.db.models import ArslanMessage, SpawnCapability

    await session.execute(
        sa_update(ArslanMessage)
        .where(ArslanMessage.spawn_id == spawn_id)
        .values(spawn_id=None)
    )
    await session.execute(
        sa_delete(SpawnCapability).where(SpawnCapability.spawn_id == spawn_id)
    )
    await session.delete(spawn)  # ORM cascades chat_messages + feedback
    await session.commit()
    return True


async def load_all_spawns() -> list[Spawn]:
    """Load every Spawn row ordered by id, managing its own session.

    Unlike the other functions in this module (which accept a session as a
    parameter), this helper opens and closes its own AsyncSessionLocal session.
    Use it in call-sites that don't already hold an open session — for example,
    the orchestrator's dedup check before create.
    """
    from server.db import session as db_session

    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(select(Spawn).order_by(Spawn.id))
        return list(rows.scalars().all())


async def create_spawn(session: AsyncSession, **fields) -> Spawn:
    """Insert a spawn row. Used by the build WebSocket and test seeding."""
    spawn = Spawn(**fields)
    session.add(spawn)
    await session.commit()
    await session.refresh(spawn)
    return spawn


def emit_skillpack(spawns_dir, spawn_name: str, draft: dict, system_prompt: str):
    """Write the spawn's skill-pack files to disk (storage model A: working copy).

    Server create persists DB rows AND emits the on-disk skill-pack, so the spawn
    is a portable artifact with a SKILL.md that Tier-1 evolution can rewrite.
    """
    from pathlib import Path

    from arslan.models import DomainInfo, PersonaSpec, SpawnBlueprint, SpawnRequirements
    from arslan.spawn.manager import SpawnManager

    domain = draft.get("domain") or "other"
    category, _, subcategory = domain.partition(".")
    requirements = SpawnRequirements(
        spawn_name=spawn_name,
        domain=DomainInfo(category=category or "other", subcategory=subcategory or None),
        capabilities=normalize_capabilities(draft.get("capabilities")),
        persona=PersonaSpec(
            role=draft.get("persona_role") or spawn_name,
            tone=draft.get("persona_tone") or "",
        ),
    )
    blueprint = SpawnBlueprint(
        requirements=requirements,
        tools=[],
        system_prompt=system_prompt,
        workflow_steps=[],
    )
    return SpawnManager(spawns_dir=Path(spawns_dir)).generate_skillpack(blueprint)


def reflect_equipment(spawns_dir, spawn_name: str, equipment: dict) -> bool:
    """Reflect a spawn's equipment into its SKILL.md (Tier-2 derived view, no drift).

    The DB equipment set stays authoritative; this writes a regenerated section so
    the portable skill-pack lists its granted capabilities.
    """
    from pathlib import Path

    from arslan.spawn.evolve import apply_tier2_capabilities

    caps = list(equipment.get("toolsets") or []) + list(equipment.get("skills") or [])
    return apply_tier2_capabilities(Path(spawns_dir) / spawn_name, caps)


async def create_from_draft(draft: dict, differentiation: str | None = None):
    """Create the spawn + equipment rows + persisted intro.

    Returns (spawn_id, spawn_name, equipment, intro). Equipment comes from the
    draft's explicit `equipment` (validated) or LLM curation over the safe menu.

    Placement rationale: lives in spawn_service (not ws/arslan.py) so that both
    the WS confirm_create path and the REST create path (api/create.py) share
    the same code path without circular imports. ws/arslan.py re-exports
    _create_from_draft as a thin alias so existing tests that import from there
    continue to work without change.
    """
    from server.db import session as db_session
    from server.db.models import ChatMessage, SpawnCapability
    from server.registry import service as registry_service
    from server.services import equipment_service

    domain = draft.get("domain") or "other"
    category, _, subcategory = domain.partition(".")
    system_prompt = build_system_prompt(draft)
    if differentiation:
        system_prompt += (
            f"\n\nSpecialization (how you differ from similar specialists): {differentiation}"
        )

    explicit = draft.get("equipment") or None
    drafter_tools = draft.get("tools")
    drafter_skills = draft.get("skills")
    drafter_mcps = draft.get("mcps")
    if explicit:
        keys = {
            "toolsets": [str(k) for k in explicit.get("toolsets") or []],
            "skills": [str(k) for k in explicit.get("skills") or []],
        }
        for k in keys["toolsets"]:
            await registry_service.assert_assignable("toolset", k)
        for k in keys["skills"]:
            await registry_service.assert_assignable("skill", k)
    elif drafter_tools is not None or drafter_skills is not None or drafter_mcps is not None:
        # L2 bridge: the drafter already mapped capabilities to the real registry.
        # MCPs are toolset rows keyed mcp_<id>, so they go in the toolsets bucket.
        keys = {
            "toolsets": [str(k) for k in (drafter_tools or [])]
                        + [str(k) for k in (drafter_mcps or [])],
            "skills": [str(k) for k in (drafter_skills or [])],
        }
        for k in keys["toolsets"]:
            await registry_service.assert_assignable("toolset", k)
        for k in keys["skills"]:
            await registry_service.assert_assignable("skill", k)
    else:
        need = " ".join(
            filter(None, [draft.get("name"), domain, draft.get("persona_role"),
                          ", ".join(draft.get("capabilities") or [])])
        )
        # curate validates every key it returns internally; no re-validation here.
        keys = await equipment_service.curate(need)
        keys = {
            "toolsets": list(keys.get("toolsets") or []) + list(keys.get("mcps") or []),
            "skills": list(keys.get("skills") or []),
        }

    async with db_session.AsyncSessionLocal() as db:
        spawn = await create_spawn_unique(
            db,
            name=draft.get("name") or "new-spawn",
            domain_category=category or "other",
            domain_subcategory=subcategory or None,
            capabilities=normalize_capabilities(draft.get("capabilities")),
            persona_role=draft.get("persona_role"),
            persona_tone=draft.get("persona_tone"),
            system_prompt=system_prompt,
            generation_level=1,
        )
        for k in keys["toolsets"]:
            db.add(SpawnCapability(spawn_id=spawn.id, kind="toolset", ref_key=k))
        for k in keys["skills"]:
            db.add(SpawnCapability(spawn_id=spawn.id, kind="skill", ref_key=k))
        await db.commit()
        spawn_id, spawn_name = spawn.id, spawn.name
        persona_role = spawn.persona_role

    from server import config

    emit_skillpack(config.settings.spawns_dir, spawn_name, draft, system_prompt)

    equipment = await registry_service.equipment_for_spawn(spawn_id)
    reflect_equipment(config.settings.spawns_dir, spawn_name, equipment)
    intro = await equipment_service.build_intro(
        name=spawn_name, persona_role=persona_role, equipment=equipment
    )
    # Intentionally a second txn: losing the intro on a crash is non-critical; the spawn+equipment txn above must not widen.
    async with db_session.AsyncSessionLocal() as db:
        db.add(ChatMessage(spawn_id=spawn_id, role="assistant", content=intro))
        await db.commit()
    return spawn_id, spawn_name, equipment, intro


async def create_spawn_unique(session: AsyncSession, *, name: str, **fields) -> Spawn:
    """Create a spawn, auto-suffixing the name (name-2, name-3, ...) to satisfy the
    UNIQUE constraint instead of raising IntegrityError on a collision."""
    base = name or "new-spawn"
    candidate = base
    suffix = 2
    while (
        await session.execute(select(Spawn.id).where(Spawn.name == candidate))
    ).first() is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return await create_spawn(session, name=candidate, **fields)
