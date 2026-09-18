"""Frozen API export, packaged offline restore and restored boot.

Only disposable homes and synthetic memories; no model or installed-app calls.
The restore coordinator runs in the binary, not through a native import UI.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

from scripts.frozen_sidecar_smoke import start, stop
from server.services import backup
from server.services.memory_deletion_manifest import decode


def assert_record_current(client):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get("/api/v1/memory/deletion-record-status")
        assert response.status_code == 200
        if response.json() == {"status": "current", "database_epoch": 1, "saved_epoch": 1}:
            return
        time.sleep(0.05)  # Bound startup/repair observation; never accept a stale record.
    raise AssertionError("Packaged deletion mirror did not become current")


def restore_packaged(binary, home, archive, target, current=None, manifest=None):
    mode = ["--current-db-path", str(current)] if current else ["--new-machine"]
    if manifest:
        mode += ["--deletion-manifest", str(manifest)]
    run = subprocess.run([str(binary), "--restore-offline", "--archive", str(archive),
                          "--new-data-dir", str(target), *mode],
                         cwd=home, input=b"", capture_output=True, timeout=30,
                         env={"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home),
                              "ARSLAN_LIVE_LLM": "0", "ARSLAN_SECRET_KEY": "frozen-smoke-synthetic-only",
                              "ARSLAN_SECRET_KEY_FILE": ""})
    assert b"ARSLAN_PORT=" not in run.stdout
    return run.returncode, json.loads(run.stdout)


def main():
    binary = Path(sys.argv[1]).resolve()
    assert binary.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert any(part.startswith(("arslan-candidate-build.", "arslan-native-candidate.")) for part in binary.parts)
    assert binary.name == "arslan-server" and binary.is_file()
    with tempfile.TemporaryDirectory(prefix="arslan-frozen-deletion-") as folder:
        root = Path(folder)
        source_home = root / "source-home"
        source_home.mkdir()
        maintenance_home = root / "maintenance-home"
        maintenance_home.mkdir()
        bodies = [{"content": text, "scope": {"kind": "global"}, "use_policy": "cloud_allowed"}
                  for text in ("Synthetic preference deleted after backup", "Synthetic preference retained for review")]
        process, client, _ = start(binary, source_home)
        try:
            entries = []
            for body in bodies:
                response = client.post("/api/v1/memory/entries", json=body)
                assert response.status_code == 201
                entries.append(response.json())
        finally:
            client.close()
            assert stop(process) == 0
        source = source_home / "Library/Application Support/Arslan"
        archive = root / "old.zip"
        backup.create(source, archive)
        original = archive.read_bytes()

        process, client, _ = start(binary, source_home)
        try:
            response = client.delete(f"/api/v1/memory/entries/{entries[0]['id']}",
                                     params={"expected_version": entries[0]["version"]})
            assert response.status_code == 200
            endpoint = "/api/v1/memory/deletion-manifest"
            assert client.get(endpoint, headers={"Authorization": "Bearer invalid-synthetic-token"}).status_code == 401
            response = client.get(endpoint)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["content-disposition"] == 'attachment; filename="arslan-deletion-manifest.json"'
            payload = response.content
            value = decode(payload)
            assert value["deletion_epoch"] == 1 and len(value["deletions"]) == 1
            assert value["deletions"][0]["entry_id"] == entries[0]["id"]
            assert all(body["content"].encode() not in payload for body in bodies)
            assert b"digest_key" not in payload
            assert_record_current(client)
            ledger = source / ".memory-deletion-ledgers" / (value["instance_id"] + ".json")
            assert ledger.stat().st_mode & 0o777 == 0o600
            assert decode(ledger.read_bytes()) == value
            duplicate = subprocess.run([str(binary)], cwd=source_home, input=b"", capture_output=True,
                                       timeout=15, env={"PATH": "/usr/bin:/bin", "HOME": str(source_home),
                                                        "TMPDIR": str(source_home), "ARSLAN_LIVE_LLM": "0",
                                                        "ARSLAN_SECRET_KEY": "frozen-smoke-synthetic-only",
                                                        "ARSLAN_SECRET_KEY_FILE": ""})
            assert duplicate.returncode == 1
            assert duplicate.stdout == b"ARSLAN_ERROR=data_profile_in_use\n"
            assert client.get("/api/v1/settings").status_code == 200
            blocked = root / "blocked-restore"
            code, result = restore_packaged(binary, maintenance_home, archive, blocked, source / "arslan.db")
            assert code == 1 and result == {"ok": False, "code": "data_profile_in_use"}
            assert not blocked.exists() and not list(root.glob(".arslan-restore-*"))
        finally:
            client.close()
            assert stop(process) == 0

        ledger.unlink()  # Only this disposable fixture: simulate the mirror crash gap.
        process, client, _ = start(binary, source_home)
        try:
            assert_record_current(client)
            assert decode(ledger.read_bytes()) == value
        finally:
            client.close()
            assert stop(process) == 0

        restored_home = root / "restored-home"
        restored = restored_home / "Library/Application Support/Arslan"
        code, response = restore_packaged(binary, maintenance_home, archive, restored, source / "arslan.db")
        assert code == 0 and response["ok"] is True
        result = response["result"]
        assert result["deletion_record_selection"]["local_ledger_present"] is True
        assert result["deletion_record_selection"]["sources_checked"] == ["current_database", "local_ledger"]
        assert result["memory_review"]["quarantined_entries"] == 2
        assert result["deletion_reconciliation"]["deleted_entries"] == 1
        # A new-machine import also exercises bounded decoding inside the binary.
        exported_record = root / "export.json"
        exported_record.write_bytes(payload)
        imported_target = root / "imported"
        code, imported = restore_packaged(binary, maintenance_home, archive, imported_target,
                                          manifest=exported_record)
        assert code == 0 and imported["result"]["deletion_reconciliation"]["deleted_entries"] == 1
        assert imported["result"]["deletion_record_selection"] == {"selected_source": "imported_manifest"}
        inode = imported_target.stat().st_ino
        code, refused = restore_packaged(binary, maintenance_home, archive, imported_target,
                                         manifest=exported_record)
        assert code == 1 and refused == {"ok": False, "code": "restore_refused"}
        assert imported_target.stat().st_ino == inode
        assert exported_record.read_bytes() == payload
        assert not list(maintenance_home.iterdir())  # No implicit profile, token or key bootstrap.
        with sqlite3.connect(restored / "arslan.db") as db:
            assert db.execute("SELECT content FROM memory_revisions WHERE entry_id=?", (entries[0]["id"],)).fetchall() == [(None,)]
        previous = None
        for _ in range(2):
            process, client, _ = start(binary, restored_home)
            try:
                response = client.get(f"/api/v1/memory/entries/{entries[0]['id']}")
                assert response.status_code == 200
                deleted = response.json()
                assert deleted["status"] == "deleted" and deleted["content"] is None
                if previous is not None:
                    assert deleted == previous
                previous = deleted
                response = client.get(f"/api/v1/memory/entries/{entries[1]['id']}")
                assert response.status_code == 200
                retained = response.json()
                assert retained["status"] == "quarantined" and retained["content"] == bodies[1]["content"]
                assert retained["use_policy"] == "local_only" and retained["confirmed_at"] is None
                response = client.post("/api/v1/memory/entries", json=bodies[0])
                assert response.status_code == 409
                assert response.json() == {"detail": {"code": "memory_previously_deleted"}}
                exported = client.get(endpoint)
                assert exported.status_code == 200 and decode(exported.content) == value
                assert_record_current(client)
            finally:
                client.close()
                assert stop(process) == 0
        assert archive.read_bytes() == original
    print(json.dumps({"frozen_deletion_export_and_restored_boot": "passed",
                      "auth_and_private_metadata_only": True, "old_archive_unchanged": True,
                      "deleted_content_absent_and_resave_refused": True,
                      "other_memory_retained_but_quarantined": True,
                      "stable_across_two_restored_boots": True,
                      "independent_record_persisted_and_startup_repaired": True,
                      "duplicate_backend_refused_without_stopping_owner": True,
                      "active_profile_restore_refused_then_stopped_restore_passed": True,
                      "current_installation_record_selection": True,
                      "packaged_new_machine_import_and_overwrite_refusal": True,
                      "restore_coordinator": "packaged", "backup_creation": "source", "native_import_ui": False,
                      "host_request_capture": False, "real_model": False, "installed_app": False}))


if __name__ == "__main__":
    main()
