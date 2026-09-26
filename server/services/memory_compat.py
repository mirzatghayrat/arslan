"""Versioned adapters for old numeric fact links, backed only by unified memory."""
from types import SimpleNamespace
from datetime import UTC

from sqlalchemy import select

from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite
from server.db.models import MemoryEntry, MemoryLegacyMap, MemoryRevision
from server.services import personal_context
from server.services.memory_repository import repository


async def fact_dto(repo, entry):
    revision = await repo.db.get(MemoryRevision, entry.current_revision_id)
    structured = revision.structured_value or {}
    return SimpleNamespace(
        id=await repo.compatibility_id(entry), entry_id=entry.id, version=entry.version,
        status=entry.status, content=revision.content or "", sensitive=entry.sensitivity != "normal",
        source="manual" if entry.confirmation_kind == "user_form" else "auto",
        confidence=entry.confidence, created_at=entry.created_at, valid_from=entry.valid_from,
        superseded_by=None, category=structured.get("category", structured.get("legacy_category")),
        label=structured.get("label", structured.get("legacy_label")),
        provenance={"source_kind": "unified_memory", "entry_id": entry.id, "status": entry.status},
    )


async def list_facts(*, include_superseded=False, include_stale=False):
    async with repository() as repo:
        statement = select(MemoryEntry).join(MemoryLegacyMap, MemoryLegacyMap.entry_id == MemoryEntry.id).where(
            MemoryLegacyMap.source_table == "user_facts", MemoryEntry.owner_id == "local",
            MemoryEntry.status != "deleted",
        )
        if not include_superseded:
            statement = statement.where(MemoryEntry.status.in_(("active", "paused") if include_stale else ("active",)))
        rows = (await repo.db.execute(statement.order_by(MemoryEntry.created_at, MemoryEntry.id))).scalars().all()
        return [await fact_dto(repo, row) for row in rows]


async def save_facts(facts):
    ctx = personal_context.current()
    # Extraction without a trusted task context has no source/scope authority.
    if ctx is None or ctx.no_learning or ctx.temporary:
        return []
    actor = ctx.actor("extractor")
    scope = MemoryScope(kind="project", id=ctx.project_id) if ctx.project_id else MemoryScope(kind="global")
    result = []
    for fact in facts:
        content = (fact.get("content") or "").strip()
        if not content:
            continue
        try:
            async with repository() as repo:
                value = await repo.create(MemoryWrite(content=content, scope=scope,
                    sensitivity="sensitive" if fact.get("sensitive") else "normal"), actor)
                result.append(await fact_dto(repo, await repo.get(value["id"])))
        except MemoryError as exc:
            if exc.code not in {"credentials_not_memory", "memory_source_deleted", "memory_previously_deleted"}:
                raise
    return result


async def add_manual_fact(content, sensitive=False):
    async with repository() as repo:
        value = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global"),
            sensitivity="sensitive" if sensitive else "normal", sensitive_acknowledged=bool(sensitive)),
            MemoryActor(origin="user"))
        return await fact_dto(repo, await repo.get(value["id"]))


async def update_fact(fact_id, content=None, sensitive=None, *, expected_version=None):
    if expected_version is None:
        raise MemoryError("memory_version_required")
    async with repository() as repo:
        try:
            entry = await repo.by_compatibility_id("user_facts", fact_id)
        except MemoryError as exc:
            if exc.code == "memory_not_found":
                return None
            raise
        revision = await repo.db.get(MemoryRevision, entry.current_revision_id)
        await repo.revise(entry.id, expected_version, MemoryWrite(
            content=revision.content if content is None else content, kind=entry.kind,
            scope=MemoryScope(kind=entry.scope_kind, id=entry.scope_id),
            sensitivity=entry.sensitivity if sensitive is None else "sensitive" if sensitive else "normal",
            sensitive_acknowledged=sensitive is True, use_policy=entry.use_policy,
            topic=(revision.structured_value or {}).get("topic"),
            valid_from=entry.valid_from.replace(tzinfo=UTC) if entry.valid_from else None,
            review_at=entry.review_at.replace(tzinfo=UTC) if entry.review_at else None,
            expires_at=entry.expires_at.replace(tzinfo=UTC) if entry.expires_at else None,
        ), MemoryActor(origin="user"))
        return await fact_dto(repo, await repo.get(entry.id))


async def delete_fact(fact_id, *, expected_version=None):
    if expected_version is None:
        raise MemoryError("memory_version_required")
    async with repository() as repo:
        try:
            entry = await repo.by_compatibility_id("user_facts", fact_id)
        except MemoryError as exc:
            if exc.code == "memory_not_found":
                return False
            raise
        await repo.delete_entry(entry.id, expected_version, MemoryActor(origin="user"))
        return True
