import copy
import json

import pytest

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.services import memory_deletion_manifest as manifest
from server.services.memory_repository import repository


def valid():
    return {"format": 1, "instance_id": "00000000-0000-4000-8000-000000000001", "deletion_epoch": 1,
            "deletions": [{"entry_id": "00000000-0000-4000-8000-000000000002", "epoch": 1,
                           "content_digest": "a" * 64, "scope_kind": "global", "scope_key": ""}]}


async def test_export_contains_only_tombstone_metadata_and_roundtrips(execution_db):
    content = "Synthetic deleted report preference"
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
        await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
    async with execution_db.kw["bind"].begin() as connection:
        payload = await connection.run_sync(manifest.export_sync)
        assert await connection.run_sync(manifest.export_sync) == payload
    result = manifest.decode(payload)
    assert content.encode() not in payload
    assert b"digest_key" not in payload and b"source_ref" not in payload
    assert result["deletion_epoch"] == 1 and len(result["deletions"]) == 1
    assert result["deletions"][0]["entry_id"] == entry["id"]


@pytest.mark.parametrize("mutation", ["extra", "text", "bool_epoch", "future_epoch", "bad_uuid", "bad_digest", "scope", "global_key", "duplicate", "wrong_rows"])
def test_invalid_metadata_fails_closed(mutation):
    value = valid()
    row = value["deletions"][0]
    if mutation == "extra":
        value["digest_key"] = "not allowed"
    elif mutation == "text":
        row["content"] = "not allowed"
    elif mutation == "bool_epoch":
        value["deletion_epoch"] = True
    elif mutation == "future_epoch":
        row["epoch"] = 2
    elif mutation == "bad_uuid":
        row["entry_id"] = "../foreign"
    elif mutation == "bad_digest":
        row["content_digest"] = "plaintext"
    elif mutation == "scope":
        row["scope_kind"] = []
    elif mutation == "global_key":
        row["scope_key"] = "unexpected"
    elif mutation == "duplicate":
        value["deletions"].append(copy.deepcopy(row))
    else:
        value["deletions"] = {}
    with pytest.raises(ValueError, match="^invalid_deletion_manifest$"):
        manifest.decode(json.dumps(value).encode())


@pytest.mark.parametrize("payload", [b'{"format":1,"format":1}', b'\xff', b'[' * 2000])
def test_malformed_json_is_bounded_and_has_no_parser_diagnostics(payload):
    with pytest.raises(ValueError, match="^invalid_deletion_manifest$"):
        manifest.decode(payload)


def test_size_and_entry_limits(monkeypatch):
    payload = json.dumps(valid()).encode()
    monkeypatch.setattr(manifest, "MAX_BYTES", len(payload) - 1)
    with pytest.raises(ValueError, match="invalid_deletion_manifest"):
        manifest.decode(payload)
    monkeypatch.setattr(manifest, "MAX_ENTRIES", 0)
    with pytest.raises(ValueError, match="invalid_deletion_manifest"):
        manifest.validate(valid())
