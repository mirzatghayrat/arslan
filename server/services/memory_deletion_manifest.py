"""Bounded deletion metadata transfer; never includes memory text or HMAC keys.

This format is not an authorization token. A restore coordinator must match the
store identity and apply it before enabling retrieval. Export alone is not a
restore reconciliation implementation.
"""
from __future__ import annotations

import json
import re
from uuid import UUID

from sqlalchemy import select

from server.db.models import MemoryDeletion, MemoryStoreState

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
