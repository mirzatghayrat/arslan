"""The packaged-install salt probe must be able to FAIL.

``packaging/fresh_install_check.py`` only ever runs against a built .app, so nothing
in CI exercises it. That is exactly the condition under which a probe rots into
decoration: it passes on every machine it is ever run on, including the broken ones,
and its green line reads as "checked".

This file does not test the packaged app. It tests the probe — against a database
produced by the REAL boot chain, then against three deliberately broken variants of
that same database, one per assertion the probe makes. A probe that cannot be shown
to fail has not been shown to check anything.
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from server.db.migrations import runner as migration_runner
from server.db.models import Base
from server.services import crypto_boot

_PACKAGING = Path(__file__).resolve().parents[2] / "packaging"


@pytest.fixture(scope="module")
def probe():
    """Import fresh_install_check as a module (it is a script, not a package member)."""
    sys.path.insert(0, str(_PACKAGING))
    try:
        yield importlib.import_module("fresh_install_check")
    finally:
        sys.path.remove(str(_PACKAGING))


async def _real_install(tmp_path, monkeypatch) -> Path:
    """A database built the way a clean first boot builds one."""
    data_dir = tmp_path / "Arslan"
    data_dir.mkdir()
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "a-real-strong-random-key-0123456789")
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(data_dir))
    import server.config as config

    importlib.reload(config)

    db = data_dir / "arslan.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(migration_runner.apply_pending)
        await conn.run_sync(crypto_boot.resolve_and_adopt_salt)
    await eng.dispose()
    return data_dir


def _run(probe_mod, data_dir: Path):
    c = probe_mod.Checks()
    conn = sqlite3.connect(f"file:{data_dir / 'arslan.db'}?mode=ro", uri=True)
    try:
        probe_mod._check_crypto_salt_location(conn, data_dir, c)
    finally:
        conn.close()
    return c


async def test_it_passes_on_a_real_clean_install(probe, tmp_path, monkeypatch):
    data_dir = await _real_install(tmp_path, monkeypatch)

    c = _run(probe, data_dir)

    assert c.failures == [], c.failures
    assert len(c.passes) == 3


async def test_it_fails_when_a_salt_file_reappears(probe, tmp_path, monkeypatch):
    # The regression it exists for: the filesystem path coming back, letting the salt
    # drift away from the ciphertext again.
    data_dir = await _real_install(tmp_path, monkeypatch)
    (data_dir / "crypto_salt").write_bytes(bytes(16))

    c = _run(probe, data_dir)

    assert any("crypto_salt file" in f for f in c.failures), c.failures


async def test_it_fails_when_the_salt_row_is_missing(probe, tmp_path, monkeypatch):
    data_dir = await _real_install(tmp_path, monkeypatch)
    conn = sqlite3.connect(data_dir / "arslan.db")
    conn.execute("DELETE FROM settings WHERE key = 'crypto_salt_b64'")
    conn.commit()
    conn.close()

    c = _run(probe, data_dir)

    assert any("stored in the database" in f for f in c.failures), c.failures


async def test_it_fails_when_a_clean_install_claims_it_lost_its_salt(
    probe, tmp_path, monkeypatch
):
    # A false data-loss alarm is its own kind of lie, and it would train someone to
    # ignore the real one.
    data_dir = await _real_install(tmp_path, monkeypatch)
    conn = sqlite3.connect(data_dir / "arslan.db")
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)",
                 (crypto_boot.SALT_LOST_MARKER_KEY, "generated-over-existing-ciphertext"))
    conn.commit()
    conn.close()

    c = _run(probe, data_dir)

    assert any("lost its salt" in f for f in c.failures), c.failures
