"""The salt resolver, driven through a real create_all + the full migration chain.

WHY THIS FILE EXISTS SEPARATELY FROM test_crypto_salt_from_db.py. That suite builds
three-column SQLite tables by hand and calls resolve_and_adopt_salt directly. Every
assertion in it can hold while the real boot is broken, because the real boot has two
things the hand-built one does not: the actual ORM schema, and migration 0039 running
BEFORE the resolver. Unit-green is not integration-right — and the specific way it
could be wrong here is not hypothetical. If the resolver ran before 0039, an install
whose salt is still an on-disk file would find no row, conclude the salt was lost, and
generate a new one. Every unit test would stay green while real users lost access.

So the sequence below is the one server/main.py's lifespan performs, in that order,
against the real models:

    Base.metadata.create_all  ->  migration_runner.apply_pending  ->  resolve_and_adopt_salt

and the load-bearing case is the third test: ciphertext written under a salt that
existed only as a FILE must still decrypt after boot, through the ordinary
settings_service read path. That is the whole promise of the relocation, and nothing
short of running the real chain can demonstrate it.
"""
from __future__ import annotations

import base64

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server import crypto
from server.db.migrations import runner as migration_runner
from server.db.migrations.versions._0039_crypto_salt_into_db import SALT_SETTING_KEY
from server.db.models import Base
from server.services import crypto_boot

FILE_SALT = bytes(range(30, 46))
SECRET = "a-real-strong-random-key-0123456789"


async def _boot(db_path, data_dir, monkeypatch):
    """Run the real boot sequence and return (engine, provenance)."""
    monkeypatch.setenv("ARSLAN_SECRET_KEY", SECRET)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(data_dir))
    import importlib

    import server.config as config

    importlib.reload(config)

    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(migration_runner.apply_pending)
        provenance = await conn.run_sync(crypto_boot.resolve_and_adopt_salt)
    return eng, provenance


async def _salt_row(eng) -> bytes | None:
    async with eng.begin() as conn:
        row = (await conn.execute(
            sa.text("SELECT value FROM settings WHERE key = :k"),
            {"k": SALT_SETTING_KEY},
        )).fetchone()
    return base64.b64decode(row[0]) if row else None


async def test_a_fresh_install_boots_and_can_encrypt(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    eng, provenance = await _boot(tmp_path / "a.db", data_dir, monkeypatch)
    try:
        assert provenance == crypto_boot.GENERATED_FRESH
        assert await _salt_row(eng) == crypto.current_salt()
        # Usable, not merely present.
        assert crypto.decrypt(crypto.encrypt("sk-fresh")) == "sk-fresh"
        # And the filesystem stayed out of it (nail ②'s invariant, asserted here too
        # because this is the first place a REAL chain could have written one).
        assert not (data_dir / "crypto_salt").exists()
    finally:
        await eng.dispose()


async def test_rebooting_the_same_database_keeps_the_same_salt(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = tmp_path / "b.db"

    eng, first = await _boot(db, data_dir, monkeypatch)
    salt_after_first = crypto.current_salt()
    token = crypto.encrypt("sk-persists")
    await eng.dispose()

    eng, second = await _boot(db, data_dir, monkeypatch)
    try:
        assert (first, second) == (crypto_boot.GENERATED_FRESH, crypto_boot.FROM_DATABASE)
        assert crypto.current_salt() == salt_after_first
        # The point of a stable salt, stated as access rather than as bytes.
        assert crypto.decrypt(token) == "sk-persists"
    finally:
        await eng.dispose()


async def test_ciphertext_written_under_a_FILE_salt_survives_the_upgrade(tmp_path, monkeypatch):
    """The load-bearing case: an existing install upgrading into the new scheme.

    Also the one that pins the ORDER. Were resolve_and_adopt_salt to run before 0039,
    it would see no salt row, decide the salt was lost, generate a replacement — and
    this decrypt would fail. A unit test that calls the resolver on its own can never
    catch that.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "crypto_salt").write_bytes(FILE_SALT)
    db = tmp_path / "c.db"

    # Write a secret the way the OLD build would have: derived from the file's salt,
    # stored through the ordinary settings path.
    monkeypatch.setenv("ARSLAN_SECRET_KEY", SECRET)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(data_dir))
    import importlib

    import server.config as config

    importlib.reload(config)
    crypto.adopt_salt(FILE_SALT, source="pre-upgrade-file")

    pre = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with pre.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(pre, expire_on_commit=False)
    from server.services import settings_service

    async with maker() as s:
        await settings_service.update_settings(s, {"search_api_key": "sk-from-before"})
    await pre.dispose()

    # Now upgrade: the real chain, with the salt still only on disk.
    eng, provenance = await _boot(db, data_dir, monkeypatch)
    try:
        assert provenance == crypto_boot.FROM_DATABASE, (
            "0039 did not adopt the on-disk salt before the resolver ran"
        )
        assert crypto.current_salt() == FILE_SALT, "the adopted salt is not the file's"

        maker = async_sessionmaker(eng, expire_on_commit=False)
        async with maker() as s:
            got = await settings_service.get_decrypted(s, "search_api_key")
            keys = {r[0] for r in (await s.execute(sa.text("SELECT key FROM settings"))).all()}

        # Read back through the ORDINARY path, not through crypto directly: what has
        # to survive is the user's access, not a byte comparison.
        assert got == "sk-from-before", "a pre-upgrade secret stopped decrypting"
        # And nothing declared this a data-loss event.
        assert crypto_boot.SALT_LOST_MARKER_KEY not in keys
    finally:
        await eng.dispose()


async def test_an_install_whose_salt_vanished_is_marked_by_the_real_chain(tmp_path, monkeypatch):
    """The other side, end to end: ciphertext present, salt gone.

    Without this, the test above could pass because the resolver never marks anything.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = tmp_path / "d.db"

    monkeypatch.setenv("ARSLAN_SECRET_KEY", SECRET)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(data_dir))
    import importlib

    import server.config as config

    importlib.reload(config)
    crypto.adopt_salt(FILE_SALT, source="pre-upgrade-file")

    pre = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with pre.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(pre, expire_on_commit=False)
    from server.services import settings_service

    async with maker() as s:
        await settings_service.update_settings(s, {"search_api_key": "sk-orphaned"})
    await pre.dispose()
    # ...and the salt file is NOT there this time (data dir moved, backup half-copied).

    eng, provenance = await _boot(db, data_dir, monkeypatch)
    try:
        assert provenance == crypto_boot.GENERATED_OVER_CIPHERTEXT
        async with eng.begin() as conn:
            rows = dict((await conn.execute(sa.text("SELECT key, value FROM settings"))).all())
        assert crypto_boot.SALT_LOST_MARKER_KEY in rows
        # The old ciphertext is still THERE — untouched, still a candidate for
        # recovery — even though it no longer opens.
        assert rows["search_api_key"], "the unreadable ciphertext was destroyed"
    finally:
        await eng.dispose()


async def test_main_lifespan_itself_orders_migrations_before_the_resolver(tmp_path, monkeypatch):
    """Drives server.main.lifespan, not a replica of it.

    The tests above hard-code the sequence they believe main.py performs, so they
    prove the sequence WORKS without proving main.py uses it. Reordering those two
    lines in main.py would leave all of them green while every upgrading install with
    an on-disk salt lost access. The neighbouring test for the 0006 backfill settles
    for grepping main.py's source; a source check passes on code that never runs, so
    this one boots the thing instead.
    """
    import importlib

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "crypto_salt").write_bytes(FILE_SALT)
    db = tmp_path / "life.db"

    monkeypatch.setenv("ARSLAN_SECRET_KEY", SECRET)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ARSLAN_DB_PATH", str(db))
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    import server.config as config

    importlib.reload(config)

    eng = create_async_engine(f"sqlite+aiosqlite:///{db}")
    maker = async_sessionmaker(eng, expire_on_commit=False)
    import server.db.session as db_session
    import server.main as main

    monkeypatch.setattr(main, "engine", eng)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    # Start from "no salt installed", so a pass cannot be inherited from the conftest.
    crypto.adopt_salt(bytes(16), source="deliberately-wrong")

    from fastapi import FastAPI

    async with main.lifespan(FastAPI()):
        pass
    await eng.dispose()

    # 0039 ran first and adopted the file's salt; the resolver then found a row.
    assert crypto.salt_provenance() == crypto_boot.FROM_DATABASE
    assert crypto.current_salt() == FILE_SALT
