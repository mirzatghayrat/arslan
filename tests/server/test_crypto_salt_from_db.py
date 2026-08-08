"""Derivation reads the salt from the database, and refuses to guess one.

THE RULE THIS PINS. ``crypto`` no longer touches the filesystem to find its PBKDF2
salt. Boot resolves it once and installs it; if that did not happen, deriving a key
raises. The temptation is to fall back to something — the old file, the fixed
``_FALLBACK_SALT`` constant, a fresh random value — and every one of those is how the
original defect worked: a *stable* wrong key opens nothing, and anything newly written
under it becomes unreadable the moment the real salt comes back. So "raise" is the
feature, and the first test here is the one that matters most.

THE OTHER HALF, which is easy to leave out. An install whose salt row is missing while
its tables already hold ciphertext has LOST the salt. Boot has to keep working — the
user must be able to enter a new key — but that fact cannot evaporate. So it is
recorded durably at the moment it is detected, not inferred later from an absence that
the very act of booting removes.
"""
from __future__ import annotations

import base64
import importlib

import pytest
import sqlalchemy as sa

from server import crypto
from server.db.migrations.versions._0039_crypto_salt_into_db import SALT_SETTING_KEY

SALT_A = bytes(range(16))
SALT_B = bytes(range(200, 216))
REAL_SECRET = "a-real-strong-random-key-0123456789"


@pytest.fixture
def fresh_crypto(monkeypatch, tmp_path):
    """A crypto module with NO salt installed, and a real secret configured.

    Reloaded because the process-wide salt is module state and the conftest
    installs one for every other test; this suite is specifically about the
    un-installed case.
    """
    monkeypatch.setenv("ARSLAN_SECRET_KEY", REAL_SECRET)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    import server.config as config

    importlib.reload(config)
    mod = importlib.reload(crypto)
    yield mod
    importlib.reload(config)
    importlib.reload(crypto)


def _db(tmp_path, *, tables=("settings",)):
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'boot.db'}")
    with eng.begin() as c:
        if "settings" in tables:
            c.exec_driver_sql(
                "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if "provider_configs" in tables:
            c.exec_driver_sql(
                "CREATE TABLE provider_configs (id INTEGER PRIMARY KEY, api_key TEXT)")
        if "mcp_servers" in tables:
            c.exec_driver_sql(
                "CREATE TABLE mcp_servers (id INTEGER PRIMARY KEY, env TEXT)")
    return eng


def _rows(eng) -> dict[str, str]:
    with eng.begin() as c:
        return dict(c.exec_driver_sql("SELECT key, value FROM settings").fetchall())


def _resolve(eng) -> str:
    from server.services import crypto_boot

    with eng.begin() as c:
        return c.exec_driver_sql("SELECT 1").scalar() and crypto_boot.resolve_and_adopt_salt(c)


class TestRefusesToGuess:
    def test_deriving_without_an_installed_salt_raises(self, fresh_crypto):
        # THE assertion of this change. A fallback here would be indistinguishable
        # from working until someone's real salt reappeared and their newly-written
        # secrets turned out to be unreadable.
        with pytest.raises(fresh_crypto.CryptoNotInitializedError):
            fresh_crypto.encrypt("sk-nope")
        with pytest.raises(fresh_crypto.CryptoNotInitializedError):
            fresh_crypto.decrypt("gAAAAA-irrelevant")

    def test_a_salt_file_on_disk_is_not_consulted(self, fresh_crypto, tmp_path):
        # The old derivation read <data_dir>/crypto_salt. A leftover file must now be
        # inert; if it were still read, this would silently keep working and the
        # whole relocation would be cosmetic.
        (tmp_path / "crypto_salt").write_bytes(SALT_B)

        with pytest.raises(fresh_crypto.CryptoNotInitializedError):
            fresh_crypto.encrypt("sk-nope")

    def test_a_too_short_salt_is_rejected_rather_than_padded(self, fresh_crypto):
        with pytest.raises(ValueError):
            fresh_crypto.adopt_salt(b"short", source="test")


class TestDerivationUsesTheInstalledSalt:
    def test_round_trip(self, fresh_crypto):
        fresh_crypto.adopt_salt(SALT_A, source="test")
        assert fresh_crypto.decrypt(fresh_crypto.encrypt("sk-live")) == "sk-live"

    def test_a_different_salt_yields_a_different_key(self, fresh_crypto):
        # Two-sided, and the reason the salt matters at all: same secret, different
        # salt, no access. Without this, "reads the salt" could be true while the
        # salt made no difference to the key.
        fresh_crypto.adopt_salt(SALT_A, source="test")
        token = fresh_crypto.encrypt("sk-live")

        fresh_crypto.adopt_salt(SALT_B, source="test")
        with pytest.raises(Exception):
            fresh_crypto.decrypt(token)

    def test_provenance_is_reported(self, fresh_crypto):
        fresh_crypto.adopt_salt(SALT_A, source="database")
        assert fresh_crypto.salt_provenance() == "database"


class TestBootResolution:
    def test_an_existing_row_is_adopted_verbatim(self, fresh_crypto, tmp_path):
        eng = _db(tmp_path)
        with eng.begin() as c:
            c.exec_driver_sql("INSERT INTO settings (key, value) VALUES (?, ?)",
                              (SALT_SETTING_KEY, base64.b64encode(SALT_A).decode()))

        source = _resolve(eng)

        assert source == "database"
        assert fresh_crypto.current_salt() == SALT_A

    def test_a_fresh_install_generates_and_persists(self, fresh_crypto, tmp_path):
        eng = _db(tmp_path)

        source = _resolve(eng)

        assert source == "generated-fresh-install"
        stored = base64.b64decode(_rows(eng)[SALT_SETTING_KEY])
        assert stored == fresh_crypto.current_salt(), "installed salt was not the one persisted"
        assert len(stored) >= 16

    def test_the_second_boot_reads_what_the_first_wrote(self, fresh_crypto, tmp_path):
        eng = _db(tmp_path)
        first = _resolve(eng)
        salt_after_first = fresh_crypto.current_salt()

        second = _resolve(eng)

        assert (first, second) == ("generated-fresh-install", "database")
        assert fresh_crypto.current_salt() == salt_after_first, "salt rotated on reboot"

    def test_no_salt_file_is_written_anywhere(self, fresh_crypto, tmp_path):
        eng = _db(tmp_path)
        _resolve(eng)
        fresh_crypto.encrypt("sk-live")

        assert not (tmp_path / "crypto_salt").exists()


class TestSaltLostIsRecordedDurably:
    @pytest.mark.parametrize("seed", [
        ("settings", "INSERT INTO settings (key, value) VALUES ('search_api_key', 'gAAAAcipher')"),
        ("provider_configs", "INSERT INTO provider_configs (id, api_key) VALUES (1, 'gAAAAcipher')"),
        ("mcp_servers", "INSERT INTO mcp_servers (id, env) VALUES (1, 'gAAAAcipher')"),
    ])
    def test_generating_over_existing_ciphertext_is_marked(self, fresh_crypto, tmp_path, seed):
        table, insert = seed
        eng = _db(tmp_path, tables=("settings", "provider_configs", "mcp_servers"))
        with eng.begin() as c:
            c.exec_driver_sql(insert)

        source = _resolve(eng)

        assert source == "generated-over-existing-ciphertext", f"missed ciphertext in {table}"
        from server.services import crypto_boot

        marker = _rows(eng).get(crypto_boot.SALT_LOST_MARKER_KEY)
        assert marker, "the lost-salt fact was not recorded durably"

    def test_a_fresh_install_gets_no_marker(self, fresh_crypto, tmp_path):
        # The other side. A marker written unconditionally would make every new
        # install look like a data-loss event, and the warning would stop meaning
        # anything the first time it mattered.
        eng = _db(tmp_path, tables=("settings", "provider_configs", "mcp_servers"))

        _resolve(eng)

        from server.services import crypto_boot

        assert crypto_boot.SALT_LOST_MARKER_KEY not in _rows(eng)

    def test_an_empty_secret_value_is_not_ciphertext(self, fresh_crypto, tmp_path):
        # settings_service stores "" for a cleared key. Treating that as ciphertext
        # would mark a perfectly healthy install as having lost its salt.
        eng = _db(tmp_path, tables=("settings", "provider_configs", "mcp_servers"))
        with eng.begin() as c:
            c.exec_driver_sql(
                "INSERT INTO settings (key, value) VALUES ('search_api_key', '')")

        assert _resolve(eng) == "generated-fresh-install"

    def test_missing_tables_are_survived(self, fresh_crypto, tmp_path):
        # A partially-created database (first boot, create_all mid-flight) must not
        # take the boot down, and must not be read as "ciphertext present".
        eng = _db(tmp_path, tables=("settings",))

        assert _resolve(eng) == "generated-fresh-install"


class TestACorruptSaltRowIsNotAbsent:
    """The branch a mutation caught me leaving untested.

    Reading a damaged salt row as "no salt" is the worst available behaviour: boot
    would generate a replacement, write it over the damaged one, and the value that
    might still have opened the existing ciphertext would be gone for good. Loud
    refusal keeps the row — and the data — repairable.
    """

    @pytest.mark.parametrize("stored", [
        "!!! not base64 !!!",                        # non-alphabet characters
        base64.b64encode(b"tooshort").decode(),      # valid base64, only 8 bytes
    ])
    def test_it_raises_and_writes_nothing(self, fresh_crypto, tmp_path, stored):
        from server.services import crypto_boot

        eng = _db(tmp_path, tables=("settings", "provider_configs", "mcp_servers"))
        with eng.begin() as c:
            c.exec_driver_sql("INSERT INTO settings (key, value) VALUES (?, ?)",
                              (SALT_SETTING_KEY, stored))
            c.exec_driver_sql(
                "INSERT INTO settings (key, value) VALUES ('search_api_key', 'gAAAAc')")

        with pytest.raises(fresh_crypto.CryptoNotInitializedError):
            _resolve(eng)

        # The damaged value is still there, unreplaced, and no marker was invented.
        rows = _rows(eng)
        assert rows[SALT_SETTING_KEY] == stored, "the corrupt salt row was overwritten"
        assert crypto_boot.SALT_LOST_MARKER_KEY not in rows


class TestNoSettingsTableAtAll:
    """The remaining branch. Added because M5 caught one untested branch in this
    file and the lesson generalises: an ``if`` nobody exercises is an assertion
    about behaviour nobody has seen.

    A database with no settings table has nowhere to read or write a salt. The
    honest outcome is to install NOTHING — so a later decrypt raises — rather than
    to guess, which is the same rule as everywhere else here.
    """

    def test_nothing_is_installed_and_nothing_raises_at_boot(self, fresh_crypto, tmp_path):
        eng = sa.create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
        with eng.begin() as c:
            c.exec_driver_sql("CREATE TABLE unrelated (x INTEGER)")

        with eng.begin() as c:
            from server.services import crypto_boot

            source = crypto_boot.resolve_and_adopt_salt(c)

        assert source == "unavailable"
        # Boot survived, but derivation must still refuse rather than improvise.
        assert fresh_crypto.salt_provenance() is None
        with pytest.raises(fresh_crypto.CryptoNotInitializedError):
            fresh_crypto.encrypt("sk-nope")
