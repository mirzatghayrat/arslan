"""Frozen API export and boot after source-coordinated deletion-aware restore.

Only disposable homes and synthetic memories; no model or installed-app calls.
The restore service runs from source, not through a native restore/import UI.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from scripts.frozen_sidecar_smoke import start, stop
from server.services import backup
from server.services.memory_deletion_manifest import decode


def main():
    binary = Path(sys.argv[1]).resolve()
    assert binary.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert any(part.startswith(("arslan-candidate-build.", "arslan-native-candidate.")) for part in binary.parts)
    assert binary.name == "arslan-server" and binary.is_file()
    with tempfile.TemporaryDirectory(prefix="arslan-frozen-deletion-") as folder:
        root = Path(folder)
        source_home = root / "source-home"
        source_home.mkdir()
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
        finally:
            client.close()
            assert stop(process) == 0

        restored_home = root / "restored-home"
        restored = restored_home / "Library/Application Support/Arslan"
        result = backup.restore(archive, restored, deletion_manifest=payload)
        assert result["memory_review"]["quarantined_entries"] == 2
        assert result["deletion_reconciliation"]["deleted_entries"] == 1
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
            finally:
                client.close()
                assert stop(process) == 0
        assert archive.read_bytes() == original
    print(json.dumps({"frozen_deletion_export_and_restored_boot": "passed",
                      "auth_and_private_metadata_only": True, "old_archive_unchanged": True,
                      "deleted_content_absent_and_resave_refused": True,
                      "other_memory_retained_but_quarantined": True,
                      "stable_across_two_restored_boots": True,
                      "restore_coordinator": "source", "native_import_ui": False,
                      "host_request_capture": False, "real_model": False, "installed_app": False}))


if __name__ == "__main__":
    main()
