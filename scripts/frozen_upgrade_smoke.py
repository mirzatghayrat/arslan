"""Upgrade a disposable old-binary profile using the candidate backend.

Both binaries must be temporary copies. Never opens an installed user profile.
Usage: python -m scripts.frozen_upgrade_smoke OLD_BINARY NEW_BINARY
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from scripts.frozen_sidecar_smoke import start, stop
from scripts.frozen_restore_smoke import database_identity
from server.services import backup


def main():
    old, new = (Path(value).resolve() for value in sys.argv[1:])
    for binary in (old, new):
        assert binary.is_relative_to(Path(tempfile.gettempdir()).resolve())
        assert any(part.startswith(("arslan-candidate-build.", "arslan-native-candidate.")) for part in binary.parts)
        assert binary.name == "arslan-server" and binary.is_file()
    assert old != new and old.read_bytes() != new.read_bytes()
    with tempfile.TemporaryDirectory(prefix="arslan-frozen-upgrade-") as folder:
        home = Path(folder)
        process, client, old_token = start(old, home)
        try:
            response = client.put("/api/v1/settings", json={"language": "fr"})
            assert response.status_code == 200 and response.json()["language"] == "fr"
            response = client.post("/api/v1/settings/provider-configs", json={
                "label": "Synthetic upgrade fixture", "provider": "custom", "model": "offline-upgrade-model",
                "base_url": "http://127.0.0.1:9/v1", "api_key": "synthetic-upgrade-not-a-real-key"})
            assert response.status_code == 200
            provider = response.json()
            assert provider["api_key"] != "synthetic-upgrade-not-a-real-key"
        finally:
            client.close()
            assert stop(process) == 0
        data = home / "Library/Application Support/Arslan"
        with sqlite3.connect(data / "arslan.db") as db:
            old_tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "memory_entries" not in old_tables, "fixture must exercise pre-v2 migration"
            db.execute("INSERT INTO user_facts (id,content,source,sensitive,confidence,created_at,provenance) VALUES (?,?,?,?,?,?,?)",
                       (987654, "Synthetic legacy preference: concise reports", "manual", 0, 1.0,
                        "2026-01-01 00:00:00", json.dumps({"source_kind": "manual"})))
        artifact = data / "artifacts/upgrade-fixture.txt"
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_text("Synthetic old-version artifact\n", encoding="utf-8")
        asset_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        identity = database_identity(data)
        archive = home / "pre-upgrade.zip"
        backup.create(data, archive)
        archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        for attempt in range(2):
            process, client, token = start(new, home)
            try:
                assert token == old_token
                assert client.get("/api/v1/settings").json()["language"] == "fr"
                response = client.get("/api/v1/settings/provider-configs")
                assert response.status_code == 200
                current = response.json()
                assert len(current) == 1
                for key in ("id", "label", "provider", "model", "base_url", "api_key", "is_primary"):
                    assert current[0][key] == provider[key]
                assert current[0]["key_status"] == "set"
                assert client.get("/api/v1/memory/entries").status_code == 200
            finally:
                client.close()
                assert stop(process) == 0
            assert database_identity(data) == identity
            assert hashlib.sha256(artifact.read_bytes()).hexdigest() == asset_hash
            with sqlite3.connect(data / "arslan.db") as db:
                assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                phase = db.execute("SELECT phase FROM memory_store_state WHERE id=1").fetchone()
                assert phase == ("active",)
                assert db.execute("SELECT type FROM sqlite_master WHERE name='user_facts'").fetchone() == ("view",)
                migrated = db.execute("""SELECT e.id,e.version,r.content FROM memory_legacy_map m
                    JOIN memory_entries e ON e.id=m.entry_id
                    JOIN memory_revisions r ON r.id=e.current_revision_id
                    WHERE m.source_table='user_facts' AND m.source_key='987654'""").fetchall()
                assert len(migrated) == 1 and migrated[0][1:] == (1, "Synthetic legacy preference: concise reports")
                assert db.execute("SELECT content FROM user_facts WHERE id=987654").fetchone() == (
                    "Synthetic legacy preference: concise reports",)
                assert db.execute("SELECT content FROM legacy_user_facts WHERE id=987654").fetchone() == (
                    "Synthetic legacy preference: concise reports",)
                if attempt == 0:
                    first_snapshot = migrated
                else:
                    assert migrated == first_snapshot
        process, client, token = start(new, home)
        try:
            assert token == old_token
            listed = client.get("/api/v1/facts")
            assert listed.status_code == 200
            fact = next(item for item in listed.json() if item["id"] == 987654)
            assert fact["entry_id"] == first_snapshot[0][0] and fact["version"] == 1
            unversioned = client.put("/api/v1/facts/987654", json={"content": "Must not overwrite"})
            assert unversioned.status_code == 428
            edited = client.put("/api/v1/facts/987654", json={
                "content": "Synthetic revised preference: concise tables", "expected_version": 1})
            assert edited.status_code == 200 and edited.json()["version"] == 2
            current = client.get(f"/api/v1/memory/entries/{fact['entry_id']}").json()
            assert current["version"] == 2 and current["content"] == edited.json()["content"]
            with sqlite3.connect(data / "arslan.db") as db:
                assert db.execute("SELECT content FROM legacy_user_facts WHERE id=987654").fetchone() == (
                    "Synthetic legacy preference: concise reports",)
            stale = client.delete("/api/v1/facts/987654", params={"expected_version": 1})
            assert stale.status_code == 409
            deleted = client.delete("/api/v1/facts/987654", params={"expected_version": 2})
            assert deleted.status_code == 204
        finally:
            client.close()
            assert stop(process) == 0
        # Editing retains the immutable recovery row; explicit deletion must
        # erase it as well as active/revision/index payloads, not resurrect it.
        with sqlite3.connect(data / "arslan.db") as db:
            assert db.execute("SELECT count(*) FROM legacy_user_facts WHERE id=987654").fetchone() == (0,)
            assert db.execute("SELECT status,version FROM memory_entries WHERE id=?", (fact["entry_id"],)).fetchone() == ("deleted", 3)
            assert db.execute("SELECT content FROM memory_revisions WHERE entry_id=?", (fact["entry_id"],)).fetchall() == [(None,)]
            assert db.execute("SELECT count(*) FROM memory_entries_fts WHERE entry_id=?", (fact["entry_id"],)).fetchone() == (0,)
        process, client, token = start(new, home)
        try:
            assert token == old_token
            listed = client.get("/api/v1/facts")
            assert listed.status_code == 200 and all(item["id"] != 987654 for item in listed.json())
            deleted = client.get(f"/api/v1/memory/entries/{fact['entry_id']}")
            assert deleted.status_code == 200
            assert deleted.json()["status"] == "deleted" and deleted.json()["content"] is None
        finally:
            client.close()
            assert stop(process) == 0
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_hash
    print(json.dumps({"frozen_upgrade_storage": "passed", "pre_v2_schema": True, "candidate_boots": 4,
                      "legacy_api_edit_delete_and_stale_version_guards": True,
                      "deletion_erases_recovery_revision_index_and_survives_restart": True,
                      "legacy_snapshot_retained_and_idempotent": True, "memory_v2_activation": "active",
                      "provider_ciphertext_and_salt_retained": True, "provider_key_decryptable": True,
                      "language_token_artifact_retained": True, "pre_upgrade_backup_unchanged": True,
                      "old_binary_sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
                      "new_binary_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
                      "real_model": False, "installed_app_modified": False}))


if __name__ == "__main__":
    main()
