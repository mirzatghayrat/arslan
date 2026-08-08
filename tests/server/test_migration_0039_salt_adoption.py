"""0039 adopts the on-disk PBKDF2 salt; it must never invent one.

The stakes are asymmetric in a way worth stating plainly. Adopting the wrong bytes,
or generating fresh ones, makes every stored secret undecryptable at the moment of
upgrade — the exact failure this migration exists to prevent, delivered by the fix.
Doing nothing, by contrast, leaves the install exactly as it was. So every assertion
below is written to catch a salt that CHANGED, and the absent-file case asserts that
nothing was written rather than that something sensible was.

The other half is that "no salt row, no salt file, but ciphertext present" has to stay
observable. That state is how the diagnosis tells the user which half of the key went
missing. A migration that helpfully generated a salt there would erase the evidence
and replace a legible failure with a silent one.
"""
from __future__ import annotations

import base64

import pytest
import sqlalchemy as sa

from server.db.migrations.versions import _0039_crypto_salt_into_db as m0039

KEY = m0039.SALT_SETTING_KEY
SALT_A = bytes(range(16))                      # 16 distinct bytes; b64 round-trip is visible
SALT_B = bytes(range(100, 116))                # a DIFFERENT salt, to catch overwrites


def _engine_with_settings(tmp_path, *, table: bool = True):
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm39.db'}")
    if table:
        with eng.begin() as c:
            c.exec_driver_sql(
                "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return eng


def _rows(eng) -> list[tuple[str, str]]:
    with eng.begin() as c:
        return list(c.exec_driver_sql("SELECT key, value FROM settings").fetchall())


def _run(eng) -> None:
    with eng.begin() as c:
        m0039.upgrade_sync(c)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point the single data-dir resolver at a scratch directory."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(d))
    return d


class TestAdoption:
    def test_adopts_the_file_salt_verbatim(self, tmp_path, data_dir):
        (data_dir / "crypto_salt").write_bytes(SALT_A)
        eng = _engine_with_settings(tmp_path)

        _run(eng)

        rows = _rows(eng)
        assert len(rows) == 1 and rows[0][0] == KEY
        # Verbatim is the whole point: the derived key must be bit-for-bit what it
        # was before the upgrade, so assert the DECODED bytes, not just "a row exists".
        assert base64.b64decode(rows[0][1]) == SALT_A

    def test_is_idempotent(self, tmp_path, data_dir):
        # ⚠️ This one has no independent power and the mutation run proved it: with
        # upgrade_sync stubbed to `return`, "unchanged across two runs" is satisfied
        # by no rows at all, twice, and it stayed green. It is only meaningful given
        # that adoption happens, which test_adopts_the_file_salt_verbatim pins. Kept
        # because re-running the boot chain on an existing install is the real
        # scenario, but it is not the assertion that would catch a broken migration.
        (data_dir / "crypto_salt").write_bytes(SALT_A)
        eng = _engine_with_settings(tmp_path)

        _run(eng)
        first = _rows(eng)
        _run(eng)

        assert first, "adoption did not happen; the comparison below proves nothing"
        assert _rows(eng) == first, "second run changed the salt row"

    def test_an_existing_row_wins_over_the_file(self, tmp_path, data_dir):
        # The database is the source of truth once adopted. If a stale file with a
        # DIFFERENT salt is still lying around, letting it win would rotate the key
        # on an install that was working — the failure mode, not the fix.
        (data_dir / "crypto_salt").write_bytes(SALT_B)
        eng = _engine_with_settings(tmp_path)
        with eng.begin() as c:
            c.exec_driver_sql("INSERT INTO settings (key, value) VALUES (?, ?)",
                              (KEY, base64.b64encode(SALT_A).decode()))

        _run(eng)

        assert base64.b64decode(_rows(eng)[0][1]) == SALT_A


class TestRefusesToInvent:
    def test_absent_file_writes_nothing(self, tmp_path, data_dir):
        # No file, no row. This is the "salt was lost" state and it must stay
        # observable — a generated salt here would hide which half went missing.
        eng = _engine_with_settings(tmp_path)

        _run(eng)

        assert _rows(eng) == []

    def test_a_too_short_file_is_not_adopted(self, tmp_path, data_dir):
        # A truncated/poisoned file is not a salt. Adopting 4 bytes would pin the
        # install to a key derived from garbage and look like success.
        (data_dir / "crypto_salt").write_bytes(b"ab")
        eng = _engine_with_settings(tmp_path)

        _run(eng)

        assert _rows(eng) == []

    def test_a_directory_where_the_file_should_be_is_survived(self, tmp_path, data_dir):
        # read_bytes() on a directory raises OSError. The migration must not take
        # the whole boot down over it.
        (data_dir / "crypto_salt").mkdir()
        eng = _engine_with_settings(tmp_path)

        _run(eng)

        assert _rows(eng) == []

    def test_no_settings_table_is_survived(self, tmp_path, data_dir):
        (data_dir / "crypto_salt").write_bytes(SALT_A)
        eng = _engine_with_settings(tmp_path, table=False)

        _run(eng)  # must not raise

        with eng.begin() as c:
            names = {r[0] for r in c.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "settings" not in names


class TestTheRowStaysOutOfTheSettingsApi:
    def test_the_key_is_in_no_settings_registry(self):
        # get_settings() builds its response by walking these registries, so
        # membership — not absence of a grep hit — is what keeps the salt out of
        # GET /settings and out of the form's round-trip.
        from server.services import settings_service as ss

        for registry in (ss._PLAIN_KEYS, ss._SECRET_KEYS, ss._INT_KEYS):
            assert KEY not in registry, f"salt key leaked into {registry}"

    async def test_get_settings_does_not_return_it(self, tmp_path, monkeypatch):
        # The behavioural half. A registry could grow a derived member later; this
        # asserts the observable response, which is what a caller actually sees.
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from server.db.models import Base, Setting
        from server.services import settings_service as ss

        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(eng, expire_on_commit=False)
        async with maker() as db:
            db.add(Setting(key=KEY, value=base64.b64encode(SALT_A).decode()))
            await db.commit()
            out = await ss.get_settings(db)
        await eng.dispose()

        assert KEY not in out
