"""The shared test databases are on memory v2, as every launch leaves them since v0.1.40 (C2a).

storage_boot.initialize activates v2 on every launch, so a test on a v1 database exercises code no
user runs. Files that still need v1 from the shared fixtures ask for it with the memory_v1 marker
(pyproject.toml); this pins which files use the marker, and that the shared fixtures build an
active v2 database.

What it does not catch: a test that builds its own database with Base.metadata.create_all, or that
imports conftest's _legacy_schema directly, gets v1 without the marker.
"""
from pathlib import Path

from server.services.memory_repository import is_active
from tests.server.conftest import build_ws_client

TESTS = Path(__file__).resolve().parents[1]

# The code these test still has a v1 path. C2a-2 deletes it, and these entries with it.
UNTIL_C2A_2 = {
    "server/test_brain_payload_shape.py",
    "server/test_brain_undo_supersede.py",
    "server/test_curation_proposals.py",
    "server/test_memory_proposals_api.py",
    "server/test_spawn_preferences_api.py",
}
# Activation and migration from v1 are what these test: kept while that code exists.
PERMANENT = {
    "server/test_memory_activation.py",
    "server/test_memory_deletion_manifest.py",     # its "legacy" case only
}


def test_only_the_listed_files_ask_for_memory_v1():
    asking = {path.relative_to(TESTS).as_posix() for path in TESTS.rglob("*.py")
              if "memory_v1" in path.read_text(encoding="utf-8")}
    asking -= {"server/conftest.py", "server/test_memory_v1_marker_scope.py"}
    assert asking == UNTIL_C2A_2 | PERMANENT


async def test_the_execution_database_is_on_memory_v2(execution_db):
    assert await is_active()


async def test_the_client_database_is_on_memory_v2(client):
    async with client.db_maker() as db:
        assert await is_active(db)


async def test_the_w_database_is_on_memory_v2(wdb):
    assert await is_active()


def test_the_websocket_client_database_is_on_memory_v2(tmp_path, monkeypatch, portal):
    seen = []

    async def seed(maker):
        async with maker() as db:
            seen.append(await is_active(db))
    build_ws_client(portal, tmp_path, monkeypatch, seed, env={"ARSLAN_API_TOKEN": ""})
    assert seen == [True]


async def test_the_shared_database_makes_no_upgrade_backup(execution_db, tmp_path):
    # Boot checks for an upgrade backup on the empty file before create_all; the fixture did it
    # after (inside apply_pending), saw a "pending upgrade" and zipped every fresh test database.
    assert not (tmp_path / "backups").exists()
