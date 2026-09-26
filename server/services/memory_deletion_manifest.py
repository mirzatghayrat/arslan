"""Bounded deletion metadata transfer; never includes memory text or HMAC keys.

This format is not an authorization token. A restore coordinator must match the
store identity and apply it before enabling retrieval. Export alone is not a
restore reconciliation implementation.
"""
from __future__ import annotations

import json
import re
from uuid import UUID, uuid4
from datetime import datetime

from sqlalchemy import select, text, update, delete, insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from server.db.models import (MemoryDeletion, MemoryStoreState, MemoryEntry, MemoryRevision,
                              MemorySource, MemoryProposal, MemoryLegacyMap)

MAX_BYTES = 4 * 1024 * 1024
MAX_ENTRIES = 10_000
_SCOPES = {"global", "project", "domain", "expert", "task"}


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError("invalid_deletion_manifest")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError("invalid_deletion_manifest") from exc


def validate(value: object) -> dict:
    """Exact schema: unknown fields cannot smuggle text/credentials into export."""
    if not isinstance(value, dict) or set(value) != {"format", "instance_id", "deletion_epoch", "deletions"}:
        raise ValueError("invalid_deletion_manifest")
    if type(value["format"]) is not int or value["format"] != 1:
        raise ValueError("invalid_deletion_manifest")
    _uuid(value["instance_id"])
    epoch = value["deletion_epoch"]
    if type(epoch) is not int or not 0 <= epoch <= 2**63 - 1:
        raise ValueError("invalid_deletion_manifest")
    rows = value["deletions"]
    if not isinstance(rows, list) or len(rows) > MAX_ENTRIES:
        raise ValueError("invalid_deletion_manifest")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"entry_id", "epoch", "content_digest", "scope_kind", "scope_key"}:
            raise ValueError("invalid_deletion_manifest")
        _uuid(row["entry_id"])
        if type(row["epoch"]) is not int or not 1 <= row["epoch"] <= epoch:
            raise ValueError("invalid_deletion_manifest")
        if not isinstance(row["content_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["content_digest"]):
            raise ValueError("invalid_deletion_manifest")
        kind, key = row["scope_kind"], row["scope_key"]
        if not isinstance(kind, str) or kind not in _SCOPES or not isinstance(key, str) or len(key) > 100:
            raise ValueError("invalid_deletion_manifest")
        if (kind == "global" and key != "") or (kind != "global" and not key.strip()):
            raise ValueError("invalid_deletion_manifest")
        identity = (row["content_digest"], kind, key)
        if identity in seen:
            raise ValueError("invalid_deletion_manifest")
        seen.add(identity)
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_deletion_manifest")
        result[key] = value
    return result


def decode(payload: bytes) -> dict:
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise ValueError("invalid_deletion_manifest")
    try:
        return validate(json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid_deletion_manifest") from exc


def export_sync(connection) -> bytes:
    """Read inside a caller-owned snapshot transaction; no file or network I/O."""
    state = connection.execute(select(MemoryStoreState.instance_id, MemoryStoreState.deletion_epoch)
                               .where(MemoryStoreState.id == 1)).mappings().one_or_none()
    if state is None:
        raise ValueError("deletion_store_not_initialized")
    rows = connection.execute(select(
        MemoryDeletion.instance_id, MemoryDeletion.entry_id, MemoryDeletion.epoch,
        MemoryDeletion.content_digest, MemoryDeletion.scope_kind, MemoryDeletion.scope_key,
    ).order_by(MemoryDeletion.epoch, MemoryDeletion.id).limit(MAX_ENTRIES + 1)).mappings().all()
    if len(rows) > MAX_ENTRIES or any(row["instance_id"] != state["instance_id"] for row in rows):
        raise ValueError("invalid_deletion_manifest")
    value = validate({"format": 1, **dict(state), "deletions": [
        {key: value for key, value in row.items() if key != "instance_id"} for row in rows]})
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("invalid_deletion_manifest")
    return payload


def reconcile_staged_sync(connection, payload: bytes) -> dict:
    """Only a quarantined staged restore; caller must commit before installing it."""
    value = decode(payload)
    state = connection.execute(select(MemoryStoreState.__table__).where(MemoryStoreState.id == 1)).mappings().one_or_none()
    if state is None or value["instance_id"] != state["instance_id"]:
        raise ValueError("deletion_manifest_store_mismatch")
    if value["deletion_epoch"] < state["deletion_epoch"]:
        raise ValueError("deletion_manifest_stale")
    tables = set(connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
    if "memory_restore_guard" not in tables or connection.execute(text(
            "SELECT applied FROM memory_restore_guard WHERE id=1")).scalar() != 1:
        raise ValueError("deletion_reconciliation_requires_quarantined_restore")
    ids = {row["entry_id"] for row in value["deletions"]}
    fingerprints = {(row["content_digest"], row["scope_kind"], row["scope_key"]) for row in value["deletions"]}
    import hashlib
    import hmac
    from arslan.companion.content_policy import normalized_memory
    candidates = connection.execute(select(MemoryEntry.__table__).where(MemoryEntry.status != "deleted")).mappings().all()
    matched = []
    for entry in candidates:
        contents = connection.execute(select(MemoryRevision.content).where(MemoryRevision.entry_id == entry["id"])).scalars()
        digests = {hmac.new(bytes.fromhex(state["digest_key"]), normalized_memory(content).encode(), hashlib.sha256).hexdigest()
                   for content in contents if content}
        if entry["id"] in ids or any((digest, entry["scope_kind"], entry["scope_id"] or "") in fingerprints for digest in digests):
            matched.append(entry)
    # Restore already invalidates old source identities, prompts, summaries and
    # the search index. Preserve that quarantine; reconciliation only removes.
    connection.execute(update(MemoryStoreState).where(MemoryStoreState.id == 1).values(phase="maintenance"))
    for entry in matched:
        key, revision, version = entry["id"], str(uuid4()), entry["version"] + 1
        mapping = connection.execute(select(MemoryLegacyMap.__table__).where(MemoryLegacyMap.entry_id == key)).mappings().one_or_none()
        if mapping and mapping["migration_note"] != "v2_alias":
            table, source_key = mapping["source_table"], mapping["source_key"]
            if table in {"user_facts", "learnings"}:
                target = "legacy_" + table if "legacy_" + table in tables else table
                connection.execute(text(f"DELETE FROM {target} WHERE id=:id"), {"id": int(source_key)})
            elif table == "spawns":
                spawn_id, index = map(int, source_key.split(":"))
                raw = connection.execute(text("SELECT memory_facts FROM spawns WHERE id=:id"), {"id": spawn_id}).scalar()
                values = json.loads(raw) if isinstance(raw, str) else list(raw or [])
                if index < len(values):
                    values[index] = ""
                    connection.execute(text("UPDATE spawns SET memory_facts=:v WHERE id=:id"), {"v": json.dumps(values), "id": spawn_id})
        connection.execute(insert(MemoryRevision).values(id=revision, entry_id=key, version=version,
                           content=None, change_reason="deleted", created_at=datetime.utcnow()))
        connection.execute(update(MemoryEntry).where(MemoryEntry.id == key).values(
            status="deleted", version=version, current_revision_id=revision, normalized_hash=None, dedup_key=None,
            confirmed_at=None, confirmation_kind=None, updated_at=datetime.utcnow()))
        connection.execute(delete(MemorySource).where(MemorySource.entry_id == key))
        connection.execute(delete(MemoryRevision).where(MemoryRevision.entry_id == key, MemoryRevision.id != revision))
        connection.execute(update(MemoryProposal).where(MemoryProposal.target_entry_id == key).values(
            candidate=None, status="dismissed", reason="target_deleted"))
    for row in value["deletions"]:
        connection.execute(sqlite_insert(MemoryDeletion).values(
            id=str(uuid4()), instance_id=state["instance_id"], **row).on_conflict_do_nothing())
    connection.execute(update(MemoryStoreState).where(MemoryStoreState.id == 1).values(
        phase=state["phase"], deletion_epoch=value["deletion_epoch"]))
    return {"applied": True, "deleted_entries": len(matched), "deletion_epoch": value["deletion_epoch"]}
