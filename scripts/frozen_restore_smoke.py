"""Synthetic backup/restore followed by actual frozen-backend boot.

The backup service runs from source; the restored database is opened by the
candidate executable. This is not an old-release upgrade or native UI test.
Run with: python -m scripts.frozen_restore_smoke /tmp/.../arslan-server
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import zipfile

from datetime import datetime
from sqlalchemy import create_engine, insert

from scripts.frozen_sidecar_smoke import start, stop
from server.db.models import ScheduledTask
from server.services import backup


def database_identity(data):
    with sqlite3.connect(data / "arslan.db") as db:
        salt = db.execute("SELECT value FROM settings WHERE key='crypto_salt_b64'").fetchone()
        providers = db.execute("SELECT id,label,provider,model,base_url,api_key,is_primary FROM provider_configs ORDER BY id").fetchall()
    assert salt and providers
    return salt, providers


def assert_schedule_paused(data):
    with sqlite3.connect(data / "arslan.db") as db:
        assert db.execute("SELECT enabled,paused_reason FROM scheduled_tasks WHERE id=987654").fetchone() == (
            0, "backup_restore_review_required")
        assert db.execute("SELECT count(*) FROM scheduled_task_runs WHERE task_id=987654").fetchone() == (0,)


def main():
    binary = Path(sys.argv[1]).resolve()
    assert binary.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert any(part.startswith(("arslan-candidate-build.", "arslan-native-candidate.")) for part in binary.parts)
    assert binary.name == "arslan-server" and binary.is_file()
    with tempfile.TemporaryDirectory(prefix="arslan-frozen-restore-") as folder:
        root = Path(folder)
        source_home = root / "source-home"
        source_home.mkdir()
        process, client, old_token = start(binary, source_home)
        try:
            saved = client.put("/api/v1/settings", json={"language": "de", "first_run_seen": True})
            assert saved.status_code == 200
            created = client.post("/api/v1/settings/provider-configs", json={
                "label": "Synthetic restore fixture", "provider": "custom",
                "model": "synthetic-offline-model", "base_url": "http://127.0.0.1:9/v1",
                "api_key": "synthetic-not-a-real-provider-key",
            })
            assert created.status_code == 200
            provider = created.json()
            assert provider["key_status"] == "set"
            assert provider["api_key"] != "synthetic-not-a-real-provider-key"
            memory_body = {"content": "Synthetic preference: use blue headings", "scope": {"kind": "global"},
                           "use_policy": "cloud_allowed"}
            response = client.post("/api/v1/memory/entries", json=memory_body)
            assert response.status_code == 201
            memory = response.json()
            assert memory["status"] == "active" and memory["version"] == 1
        finally:
            client.close()
            assert stop(process) == 0
        source = source_home / "Library/Application Support/Arslan"
        # Seed a due schedule only after stopping the source process. Never boot
        # an enabled schedule: verify restore has disabled it before launch.
        engine = create_engine(f"sqlite:///{source / 'arslan.db'}")
        try:
            with engine.begin() as connection:
                connection.execute(insert(ScheduledTask).values(
                    id=987654, name="Synthetic paused-on-restore fixture", prompt="Never dispatch this fixture",
                    target="arslan", schedule_kind="interval", interval_s=3600,
                    enabled=True, next_due_at=datetime(2000, 1, 1)))
        finally:
            engine.dispose()
        asset = source / "artifacts/restore-fixture.txt"
        asset.parent.mkdir(exist_ok=True)
        asset.write_text("Synthetic retained artifact\n", encoding="utf-8")
        expected_asset = hashlib.sha256(asset.read_bytes()).hexdigest()
        identity = database_identity(source)
        archive = root / "backup.zip"
        assert backup.create(source, archive)["secret_included"] is False
        with zipfile.ZipFile(archive) as zipped:
            assert "api_token" not in zipped.namelist()
            assert "secret_key" not in zipped.namelist()
        restored_home = root / "restored-home"
        restored = restored_home / "Library/Application Support/Arslan"
        result = backup.restore(archive, restored)
        assert result["memory_review"]["review_required"] is True
        assert result["memory_review"]["quarantined_entries"] == 1
        assert_schedule_paused(restored)
        assert not (restored / "api_token").exists()
        assert database_identity(restored) == identity
        assert hashlib.sha256((restored / asset.relative_to(source)).read_bytes()).hexdigest() == expected_asset
        process, client, new_token = start(binary, restored_home)
        try:
            assert new_token != old_token
            settings = client.get("/api/v1/settings").json()
            assert settings["language"] == "de" and settings["first_run_seen"] is True
            response = client.get("/api/v1/settings/provider-configs")
            assert response.status_code == 200
            assert response.json() == [provider]
            assert client.get("/api/v1/settings", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
            response = client.get(f"/api/v1/memory/entries/{memory['id']}")
            assert response.status_code == 200
            restored_memory = response.json()
            assert restored_memory["status"] == "quarantined" and restored_memory["version"] == 2
            assert restored_memory["confirmed_at"] is None
            assert restored_memory["use_policy"] == "local_only"
            assert restored_memory["content"] == memory_body["content"]
            stale = client.put(f"/api/v1/memory/entries/{memory['id']}", json={
                "expected_version": 1, "memory": memory_body})
            assert stale.status_code == 409
            assert stale.json() == {"detail": {"code": "memory_version_conflict"}}
        finally:
            client.close()
            assert stop(process) == 0
        assert database_identity(restored) == identity
        assert_schedule_paused(restored)
        assert hashlib.sha256((restored / asset.relative_to(source)).read_bytes()).hexdigest() == expected_asset
        process, client, restart_token = start(binary, restored_home)
        try:
            assert restart_token == new_token
            response = client.get(f"/api/v1/memory/entries/{memory['id']}")
            assert response.status_code == 200 and response.json() == restored_memory
        finally:
            client.close()
            assert stop(process) == 0
        assert_schedule_paused(restored)
    print(json.dumps({"frozen_restore_boot": "passed", "provider_ciphertext_and_salt_retained": True,
                      "provider_key_decryptable": True, "settings_and_artifact_retained": True,
                      "old_access_token_rejected": True, "backup_implementation": "source",
                      "memory_quarantined_and_stale_confirmation_rejected": True,
                      "due_schedule_paused_without_dispatch": True,
                      "quarantine_survives_second_boot_without_revision_churn": True,
                      "old_release_upgrade": False, "real_model": False, "installed_app": False}))


if __name__ == "__main__":
    main()
