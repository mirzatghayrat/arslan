"""Transactional, idempotent legacy-memory snapshot into versioned storage.

No model calls, credential reads, index requests, or legacy row modifications.
The later repository activation makes legacy writes read-only in one transition.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import uuid
from collections import Counter
from datetime import datetime

from sqlalchemy import insert, select, text, update

from arslan.companion.content_policy import contains_credential, normalized_memory
from server.db.models import (
    MemoryEntry, MemoryLegacyMap, MemoryMigrationReport, MemoryRevision,
    MemorySource, MemoryStoreState, MemorySuppression, Project,
)


def _json(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    try:
        result = json.loads(value) if value else fallback
        return result if isinstance(result, type(fallback)) else fallback
    except (ValueError, TypeError):
        return fallback


def _time(value):
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            from datetime import UTC
            return parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError):
        return None


def migrate_legacy_sync(connection, *, fault_after: int | None = None) -> dict:
    """Run inside the caller's transaction; fault_after is for crash-injection tests."""
    for model in (Project, MemoryEntry, MemoryRevision, MemorySource, MemoryLegacyMap,
                  MemoryStoreState, MemoryMigrationReport, MemorySuppression):
        model.__table__.create(connection, checkfirst=True)
    state = connection.execute(select(MemoryStoreState.__table__)).mappings().first()
    if state is None:
        connection.execute(insert(MemoryStoreState).values(
            id=1, instance_id=str(uuid.uuid4()), phase="prepared", deletion_epoch=0,
            digest_key=secrets.token_hex(32), created_at=datetime.utcnow(),
        ))
        state = connection.execute(select(MemoryStoreState.__table__)).mappings().one()
    namespace = uuid.UUID(state["instance_id"])
    from server.services.memory_restore import apply_pending_guard_sync, is_restored_sync
    restored = is_restored_sync(connection)
    if state["phase"] == "active":
        apply_pending_guard_sync(connection)
        return {"new_entries": 0, "phase": "active", "already_active": True}
    existing = {
        (row["source_table"], row["source_key"]): row
        for row in connection.execute(select(MemoryLegacyMap.__table__)).mappings()
    }
    counts, notes, relationships, migrated = Counter(), Counter(), [], 0
    now = datetime.utcnow()
    source_ids = {
        "conversation_id": set(connection.execute(text("SELECT DISTINCT conversation_id FROM arslan_messages")).scalars()),
        "spawn_id": set(connection.execute(text("SELECT id FROM spawns")).scalars()),
        "feedback_id": set(connection.execute(text("SELECT id FROM feedback")).scalars()),
        "run_id": set(connection.execute(text("SELECT id FROM runs")).scalars()),
    }

    def add(table, key, raw, *, content, kind, scope_kind, scope_id, provenance,
            sensitivity, status, author, confirmed_at=None, confirmation_kind=None,
            valid_from=None, superseded_key=None):
        nonlocal migrated
        counts[table] += 1
        source_hash = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False,
                                               default=str).encode()).hexdigest()
        old = existing.get((table, key))
        if old:
            if old["source_sha256"] != source_hash:
                raise ValueError("legacy memory changed after snapshot; review before migration")
            counts["already_mapped"] += 1
            return
        entry_id = str(uuid.uuid5(namespace, f"{table}:{key}"))
        revision_id = str(uuid.uuid5(namespace, f"{table}:{key}:revision:1"))
        source_id = str(uuid.uuid5(namespace, f"{table}:{key}:source:1"))
        restricted = contains_credential(content)
        if any(provenance.get(field) is not None and provenance[field] not in ids
               for field, ids in source_ids.items()):
            status = "quarantined"
            notes["dangling_source"] += 1
        if restricted:
            sensitivity, status = "secret", "quarantined"
            notes["credential_value_retained_only_in_legacy_recovery"] += 1
        if not content.strip():
            status = "quarantined"
            notes["empty_legacy_content"] += 1
        if restored:
            status, confirmed_at, confirmation_kind = "quarantined", None, None
            notes["backup_restore_review_required"] += 1
        created = _time(raw.get("created_at")) or now
        connection.execute(insert(MemoryEntry).values(
            id=entry_id, owner_id="local", kind=kind, scope_kind=scope_kind, scope_id=scope_id,
            status=status, current_revision_id=revision_id, version=1,
            normalized_hash=hmac.new(bytes.fromhex(state["digest_key"]),
                                     normalized_memory(content).encode(), hashlib.sha256).hexdigest(),
            sensitivity=sensitivity, use_policy="never" if restricted else "local_only",
            confidence=raw.get("confidence") if (
                isinstance(raw.get("confidence"), (int, float))
                and math.isfinite(raw["confidence"]) and 0 <= raw["confidence"] <= 1
            ) else None,
            confirmation_kind=confirmation_kind, confirmed_at=confirmed_at,
            valid_from=valid_from, created_at=created, updated_at=now,
        ))
        connection.execute(insert(MemoryRevision).values(
            id=revision_id, entry_id=entry_id, version=1, content=None if restricted else content,
            structured_value={"legacy_category": raw.get("category"), "legacy_label": raw.get("label")},
            previous_version=None, change_reason="legacy_migration_restricted" if restricted else "legacy_migration",
            created_at=created,
        ))
        # Preserve provenance structure only, not arbitrary credentials or source bodies.
        reference = {"legacy_table": table, "legacy_key": key}
        for field in ("source_kind", "conversation_id", "spawn_id", "feedback_id", "run_id",
                      "via", "edited_by_user_at", "stale"):
            value = provenance.get(field)
            if isinstance(value, (str, int, bool)) and not contains_credential(str(value)):
                reference[field] = value
        connection.execute(insert(MemorySource).values(
            id=source_id, entry_id=entry_id, revision_id=revision_id,
            source_kind="legacy", source_ref=reference, author=author,
            observed_at=_time(raw.get("created_at")), created_at=now,
        ))
        connection.execute(insert(MemoryLegacyMap).values(
            source_table=table, source_key=key, entry_id=entry_id, source_sha256=source_hash,
            migration_note="restricted" if restricted else ("needs_review" if status in {"proposed", "quarantined"} else ""),
        ))
        existing[(table, key)] = {"entry_id": entry_id, "source_sha256": source_hash}
        if superseded_key is not None:
            relationships.append((entry_id, table, str(superseded_key), scope_kind, scope_id))
        counts[f"status:{status}"] += 1
        migrated += 1
        if fault_after is not None and migrated >= fault_after:
            raise RuntimeError("synthetic migration interruption")

    for raw in connection.execute(text("SELECT * FROM user_facts ORDER BY id")).mappings():
        raw = dict(raw)
        provenance = _json(raw.get("provenance"), {})
        edited = _time(provenance.get("edited_by_user_at"))
        manual = raw.get("source") == "manual" and provenance.get("source_kind") == "manual"
        confirmed = edited or (_time(raw.get("created_at")) if manual else None)
        known_user = bool(edited or manual)
        status = "active" if known_user else ("proposed" if provenance.get("source_kind") else "quarantined")
        if provenance.get("stale"):
            status = "paused"
        if raw.get("superseded_by") is not None:
            status = "superseded"
        sensitive = raw.get("sensitive")
        sensitivity = "normal" if sensitive in (0, False) else ("sensitive" if sensitive in (1, True) else "unknown")
        add("user_facts", str(raw["id"]), raw, content=str(raw.get("content") or ""),
            kind="preference", scope_kind="global", scope_id=None, provenance=provenance,
            sensitivity=sensitivity, status=status, author="user" if known_user else "unknown",
            confirmed_at=confirmed, confirmation_kind="legacy_user_edit" if edited else ("legacy_manual" if manual else None),
            valid_from=_time(raw.get("valid_from")), superseded_key=raw.get("superseded_by"))

    for raw in connection.execute(text("SELECT * FROM learnings ORDER BY id")).mappings():
        raw = dict(raw)
        provenance = _json(raw.get("source_ref"), {})
        has_source = bool(provenance)
        provenance["source_kind"] = raw.get("source_kind") or "unknown"
        scoped = raw.get("spawn_id") is not None
        status = "superseded" if raw.get("superseded_by") is not None else ("proposed" if has_source else "quarantined")
        add("learnings", str(raw["id"]), raw, content=str(raw.get("content") or ""),
            kind="experience", scope_kind="expert" if scoped else "global",
            scope_id=str(raw["spawn_id"]) if scoped else None, provenance=provenance,
            sensitivity="unknown", status=status, author="assistant",
            valid_from=_time(raw.get("valid_from")), superseded_key=raw.get("superseded_by"))

    for row in connection.execute(text("SELECT id, memory_facts, created_at FROM spawns ORDER BY id")).mappings():
        for index, value in enumerate(_json(row["memory_facts"], [])):
            raw = {"spawn_id": row["id"], "index": index, "value": value, "created_at": row["created_at"]}
            add("spawns", f"{row['id']}:{index}", raw,
                content=value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
                kind="preference", scope_kind="expert", scope_id=str(row["id"]),
                provenance={"source_kind": "legacy_preference", "spawn_id": row["id"]},
                sensitivity="unknown", status="quarantined", author="unknown")

    for entry_id, table, key, scope_kind, scope_id in relationships:
        target = existing.get((table, key))
        target_row = None if not target else connection.execute(
            select(MemoryEntry.__table__).where(MemoryEntry.id == target["entry_id"])).mappings().first()
        if not target_row or target_row["scope_kind"] != scope_kind or target_row["scope_id"] != scope_id:
            notes["dangling_or_cross_scope_supersession"] += 1
            connection.execute(update(MemoryEntry).where(MemoryEntry.id == entry_id).values(status="quarantined"))
        else:
            connection.execute(update(MemoryEntry).where(MemoryEntry.id == entry_id).values(
                superseded_by=target["entry_id"]))
    links = dict(connection.execute(select(MemoryEntry.id, MemoryEntry.superseded_by)).all())
    cyclic, processed = set(), set()
    for start in links:
        if start in processed:
            continue
        path, seen, cursor = [], set(), start
        while cursor is not None and cursor in links and cursor not in processed:
            if cursor in seen:
                cyclic.update(path[path.index(cursor):])
                break
            seen.add(cursor)
            path.append(cursor)
            cursor = links[cursor]
        processed.update(seen)
    if cyclic:
        connection.execute(update(MemoryEntry).where(MemoryEntry.id.in_(cyclic)).values(status="quarantined"))
        notes["cyclic_supersession_entries"] = len(cyclic)
    apply_pending_guard_sync(connection)
    final_statuses = Counter(connection.execute(select(MemoryEntry.status)).scalars())
    summary = {"source_counts": dict(counts), "final_status_counts": dict(final_statuses),
               "notes": dict(notes), "new_entries": migrated,
               "phase": state["phase"], "legacy_rows_modified": 0,
               "cloud_permission_inferred": False, "instance_id": state["instance_id"]}
    if migrated or not connection.execute(select(MemoryMigrationReport.id)).first():
        connection.execute(insert(MemoryMigrationReport).values(source_version="0046", summary=summary))
    return summary
