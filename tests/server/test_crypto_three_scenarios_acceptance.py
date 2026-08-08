"""⓪'s closing gate: the three scenarios, end to end, plus the two mirror guards.

The standard, in the user's words:

    换目录启动、缺环境变量启动、备份恢复到新机器，三个场景下要么照常解密、
    要么大声说清哪半丢了 —— 不许再有静默换钥匙。

    (start from a different data directory, start with the env var missing, restore a
    backup onto a new machine: in all three, either decrypt as before or say loudly
    which half went missing — no more silently swapping keys.)

Every test below therefore asserts the SAME disjunction, never just one arm: either
the values still open, or the diagnosis names the missing half. A test that only
checked "it did not crash" would pass on the original defect, which also did not
crash — it just quietly answered "no API key set".

🔴 AND THE MIRROR GUARDS (§4.4 items 8 and 9), which only work as a pair:

  8. the recovery path writes NOTHING before a human says so
  9. the migration path REALLY migrates

Alone, either one is satisfiable by a program that does nothing at all. #8 rewards
inertness, #9 forbids it. Both, together, are the actual requirement.

These drive the real boot sequence — create_all, the migration chain, salt
resolution, the group-A sweep — because the ordering between those is itself load
bearing, and a test that calls the pieces in its own order proves the pieces work
without proving the product does.
"""
from __future__ import annotations

import base64
import hashlib
import importlib
import shutil

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server import crypto
from server.db.migrations import runner as migration_runner
from server.db.models import Base
from server.services import crypto_boot

SECRET = "the-secret-this-install-was-set-up-with"
OTHER_SECRET = "a-completely-different-secret-value-xyz"
STORED = "sk-the-key-the-user-actually-pasted"


def _reload_config(**env):
    import server.config as config

    importlib.reload(config)
    return config


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("ARSLAN_SECRET_KEY_FILE", "")   # never touch the real ~/.arslan
    yield


async def _boot(db_path, data_dir, monkeypatch, *, secret=SECRET):
    """The real sequence server/main.py performs, in its order."""
    if secret is None:
        monkeypatch.delenv("ARSLAN_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("ARSLAN_SECRET_KEY", secret)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(data_dir))
    _reload_config()

    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(migration_runner.apply_pending)
        await conn.run_sync(crypto_boot.resolve_and_adopt_salt)
        await conn.run_sync(crypto_boot.migrate_legacy_ciphertext)
    return eng


async def _diagnose(eng) -> dict:
    async with eng.begin() as conn:
        return await conn.run_sync(crypto_boot.diagnose)


async def _read_back(eng) -> str:
    """The value as the ordinary product path would read it — not via crypto directly."""
    from server.services import settings_service

    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        return await settings_service.get_decrypted(s, "search_api_key")


async def _seed(eng):
    from server.services import settings_service

    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        await settings_service.update_settings(s, {"search_api_key": STORED})


def _assert_either_opens_or_says_which_half(value: str, diag: dict, *, expect_half: str):
    """The standard itself, as one assertion.

    Passing means EITHER the secret still opens, OR the diagnosis is a real verdict
    naming a missing half. What it forbids is the third outcome the original defect
    produced: the value gone and the app reporting nothing wrong.
    """
    if value == STORED:
        assert diag["verdict"] == crypto_boot.HEALTHY, (
            f"the value opens but the diagnosis says {diag['verdict']}"
        )
        return
    assert diag["verdict"] != crypto_boot.HEALTHY, (
        "the value does NOT open and the diagnosis says everything is fine — "
        "this is the silent failure the whole spec exists to end"
    )
    assert diag["verdict"] == expect_half, diag
    assert diag["undecryptable"] >= 1, diag


class TestScenarioOneStartFromADifferentDataDirectory:
    async def test_moving_the_whole_data_dir_keeps_access(self, tmp_path, monkeypatch):
        # The salt travels inside the database now, so moving the directory that
        # CONTAINS the database cannot separate them. This is the scenario that broke
        # the author's install; it must now be a non-event.
        old = tmp_path / "old"
        old.mkdir()
        eng = await _boot(old / "arslan.db", old, monkeypatch)
        await _seed(eng)
        await eng.dispose()

        new = tmp_path / "new"
        shutil.copytree(old, new)
        eng = await _boot(new / "arslan.db", new, monkeypatch)
        try:
            _assert_either_opens_or_says_which_half(
                await _read_back(eng), await _diagnose(eng), expect_half=crypto_boot.HEALTHY)
            assert await _read_back(eng) == STORED, "moving the data dir lost the key"
        finally:
            await eng.dispose()

    async def test_pointing_at_an_empty_directory_is_not_silent(self, tmp_path, monkeypatch):
        # Taking only the DATABASE to a fresh directory (the half-move). Nothing is
        # lost here either — the salt is in the file that moved — so this asserts the
        # non-obvious half: it must NOT invent a data-loss warning.
        old = tmp_path / "old2"
        old.mkdir()
        eng = await _boot(old / "arslan.db", old, monkeypatch)
        await _seed(eng)
        await eng.dispose()

        fresh = tmp_path / "fresh"
        fresh.mkdir()
        shutil.copy(old / "arslan.db", fresh / "arslan.db")
        eng = await _boot(fresh / "arslan.db", fresh, monkeypatch)
        try:
            assert await _read_back(eng) == STORED
            assert (await _diagnose(eng))["verdict"] == crypto_boot.HEALTHY
        finally:
            await eng.dispose()


class TestScenarioTwoStartWithTheEnvVarMissing:
    async def test_it_says_the_secret_is_missing_rather_than_nothing(self, tmp_path, monkeypatch):
        home = tmp_path / "h"
        home.mkdir()
        eng = await _boot(home / "arslan.db", home, monkeypatch)
        await _seed(eng)
        await eng.dispose()

        # Boot again with no ARSLAN_SECRET_KEY and no persisted key file.
        eng = await _boot(home / "arslan.db", home, monkeypatch, secret=None)
        try:
            _assert_either_opens_or_says_which_half(
                await _read_back(eng), await _diagnose(eng),
                expect_half=crypto_boot.SECRET_MISSING)
        finally:
            await eng.dispose()

    async def test_nothing_was_rewritten_while_the_secret_was_absent(self, tmp_path, monkeypatch):
        # The silent-key-swap prohibition, in its most dangerous form: booting without
        # the secret must not re-encrypt anything under the public fallback key, which
        # would make the values unreadable even after the real secret comes back.
        home = tmp_path / "h2"
        home.mkdir()
        eng = await _boot(home / "arslan.db", home, monkeypatch)
        await _seed(eng)
        async with eng.begin() as conn:
            before = (await conn.execute(sa.text(
                "SELECT value FROM settings WHERE key='search_api_key'"))).scalar()
        await eng.dispose()

        eng = await _boot(home / "arslan.db", home, monkeypatch, secret=None)
        async with eng.begin() as conn:
            during = (await conn.execute(sa.text(
                "SELECT value FROM settings WHERE key='search_api_key'"))).scalar()
        await eng.dispose()
        assert during == before, "a keyless boot rewrote the ciphertext"

        # ...and putting the secret back restores access completely.
        eng = await _boot(home / "arslan.db", home, monkeypatch)
        try:
            assert await _read_back(eng) == STORED, "access did not come back with the secret"
            assert (await _diagnose(eng))["verdict"] == crypto_boot.HEALTHY
        finally:
            await eng.dispose()


class TestScenarioThreeRestoreABackupOntoANewMachine:
    async def test_bringing_both_halves_works(self, tmp_path, monkeypatch):
        origin = tmp_path / "origin"
        origin.mkdir()
        eng = await _boot(origin / "arslan.db", origin, monkeypatch)
        await _seed(eng)
        await eng.dispose()

        machine2 = tmp_path / "machine2"
        shutil.copytree(origin, machine2)          # the data dir
        eng = await _boot(machine2 / "arslan.db", machine2, monkeypatch)  # + the secret
        try:
            assert await _read_back(eng) == STORED
            assert (await _diagnose(eng))["verdict"] == crypto_boot.HEALTHY
        finally:
            await eng.dispose()

    async def test_bringing_the_data_but_the_WRONG_secret_says_so(self, tmp_path, monkeypatch):
        # The realistic half-restore: the data dir came across, but the new machine has
        # a different ARSLAN_SECRET_KEY. Here the secret really IS the wrong half, and
        # the diagnosis is allowed — required — to say so.
        origin = tmp_path / "origin3"
        origin.mkdir()
        eng = await _boot(origin / "arslan.db", origin, monkeypatch)
        await _seed(eng)
        await eng.dispose()

        machine2 = tmp_path / "machine3"
        shutil.copytree(origin, machine2)
        eng = await _boot(machine2 / "arslan.db", machine2, monkeypatch, secret=OTHER_SECRET)
        try:
            _assert_either_opens_or_says_which_half(
                await _read_back(eng), await _diagnose(eng), expect_half=crypto_boot.MISMATCH)
        finally:
            await eng.dispose()

    async def test_bringing_the_secret_but_not_the_database_is_a_clean_install(
        self, tmp_path, monkeypatch
    ):
        # The other half-restore. There is no ciphertext to fail on, so this must read
        # as a fresh install and NOT as data loss — a false alarm here would greet
        # every new user who happens to have set the env var first.
        home = tmp_path / "onlysecret"
        home.mkdir()
        eng = await _boot(home / "arslan.db", home, monkeypatch)
        try:
            diag = await _diagnose(eng)
            assert diag["verdict"] == crypto_boot.HEALTHY
            assert diag["undecryptable"] == 0
            async with eng.begin() as conn:
                keys = {r[0] for r in (await conn.execute(sa.text("SELECT key FROM settings"))).all()}
            assert crypto_boot.SALT_LOST_MARKER_KEY not in keys
        finally:
            await eng.dispose()


class TestGuard8TheRecoveryPathWritesNothing:
    """§4.4 #8. Pairs with Guard 9 below — neither is sufficient alone."""

    async def test_diagnose_writes_nothing_on_any_verdict(self, tmp_path, monkeypatch):
        # Across VERDICTS, not one happy path: the branch that would sneak a write in
        # is the unusual one, and "I read the code and saw no write" is exactly the
        # source-level assertion this project keeps getting burned by.
        home = tmp_path / "ro"
        home.mkdir()
        eng = await _boot(home / "arslan.db", home, monkeypatch)
        await _seed(eng)
        # Add something no key opens, to push the verdict off `healthy`.
        async with eng.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO settings (key, value) VALUES ('github_token', :v)"),
                {"v": Fernet(base64.urlsafe_b64encode(
                    hashlib.sha256(b"nobody-has-this").digest())).encrypt(b"x").decode()})
        try:
            def _guarded(c):
                original = c.exec_driver_sql

                def guard(sql, *a, **kw):
                    if sql.lstrip()[:6].upper() in ("INSERT", "UPDATE", "DELETE"):
                        raise AssertionError(f"diagnose() wrote: {sql[:70]}")
                    return original(sql, *a, **kw)

                c.exec_driver_sql = guard
                try:
                    return crypto_boot.diagnose(c)
                finally:
                    c.exec_driver_sql = original

            async with eng.begin() as conn:
                diag = await conn.run_sync(_guarded)

            # Positive half — it still did its job under the guard, so a diagnose()
            # that returned early and wrote nothing cannot pass by being inert.
            assert diag["verdict"] in crypto_boot.VERDICTS
            assert diag["undecryptable"] >= 1
        finally:
            await eng.dispose()

    async def test_boot_never_calls_the_gated_recovery(self, tmp_path, monkeypatch):
        """A value a CANDIDATE SALT CAN OPEN must still be untouched after a full boot.

        🔴 The first version of this test seeded a value encrypted under a raw Fernet
        key that no salt-derived key could ever open, so recovery could not have moved
        it even if boot had called it — the test passed because the fixture made the
        failure impossible, not because the gate held. A mutation that wired
        recover_with_salt into boot went straight through it.

        So the value is now genuinely RECOVERABLE: written under a salt that is sitting
        right there in the data dir as a candidate. If boot ever runs recovery, this
        row changes, and the assertion notices.
        """
        home = tmp_path / "gate"
        home.mkdir()
        eng = await _boot(home / "arslan.db", home, monkeypatch)
        await eng.dispose()

        # A salt the candidate machinery WILL find (data-dir file), holding a value the
        # current key cannot open. Written after the first boot so 0039 does not adopt
        # it as primary.
        candidate_salt = bytes(range(120, 136))
        (home / "crypto_salt").write_bytes(candidate_salt)
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=candidate_salt,
                         iterations=crypto._PBKDF2_ITERATIONS)
        recoverable = Fernet(base64.urlsafe_b64encode(
            kdf.derive(SECRET.encode()))).encrypt(STORED.encode()).decode()

        eng = create_async_engine(f"sqlite+aiosqlite:///{home / 'arslan.db'}")
        async with eng.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO settings (key, value) VALUES ('search_api_key', :v)"),
                {"v": recoverable})
        await eng.dispose()

        # 🔴 DRIVES server.main.lifespan, not the _boot helper above. Second time this
        # distinction has bitten in this spec: a helper that REPLICATES main.py's
        # sequence can only prove that sequence is fine, and a mutation that wires
        # recover_with_salt into the real boot sailed through this test while it used
        # the helper. What has to hold is a property of the PRODUCT's boot.
        import server.db.session as db_session
        import server.main as main
        from fastapi import FastAPI

        monkeypatch.setenv("ARSLAN_SECRET_KEY", SECRET)
        monkeypatch.setenv("ARSLAN_DATA_DIR", str(home))
        monkeypatch.setenv("ARSLAN_DB_PATH", str(home / "arslan.db"))
        monkeypatch.setenv("ARSLAN_API_TOKEN", "")
        _reload_config()

        eng = create_async_engine(f"sqlite+aiosqlite:///{home / 'arslan.db'}")
        monkeypatch.setattr(main, "engine", eng)
        monkeypatch.setattr(db_session, "AsyncSessionLocal",
                            async_sessionmaker(eng, expire_on_commit=False))
        try:
            async with main.lifespan(FastAPI()):
                pass

            # Precondition: this really IS recoverable, so "unchanged" means the gate
            # held rather than that there was nothing to do. The first version of this
            # test seeded a value NO salt-derived key could open, which made the
            # failure impossible rather than absent.
            diag = await _diagnose(eng)
            assert diag["recoverable"] == 1, diag

            async with eng.begin() as conn:
                after = (await conn.execute(sa.text(
                    "SELECT value FROM settings WHERE key='search_api_key'"))).scalar()
            assert after == recoverable, "boot rewrote a value only a candidate salt could open"
        finally:
            await eng.dispose()


class TestGuard9TheMigrationPathReallyMigrates:
    """§4.4 #9, and the reason Guard 8 cannot stand alone.

    Guard 8 rewards a program that writes nothing. This one forbids it: a legacy value
    must still open after the legacy key is REMOVED from the keyring — which read-time
    fallback, the thing d6d8afa8 mistook for a migration, cannot fake.
    """

    async def test_a_legacy_value_opens_without_the_legacy_key(self, tmp_path, monkeypatch):
        home = tmp_path / "mig"
        home.mkdir()
        monkeypatch.setenv("ARSLAN_SECRET_KEY", SECRET)
        monkeypatch.setenv("ARSLAN_DATA_DIR", str(home))
        _reload_config()

        legacy = Fernet(base64.urlsafe_b64encode(
            hashlib.sha256(SECRET.encode()).digest())).encrypt(STORED.encode()).decode()
        eng = create_async_engine(f"sqlite+aiosqlite:///{home / 'arslan.db'}")
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                sa.text("INSERT INTO settings (key, value) VALUES ('search_api_key', :v)"),
                {"v": legacy})
        await eng.dispose()

        eng = await _boot(home / "arslan.db", home, monkeypatch)
        try:
            async with eng.begin() as conn:
                stored = (await conn.execute(sa.text(
                    "SELECT value FROM settings WHERE key='search_api_key'"))).scalar()

            # THE judge. crypto.decrypt() would pass here even if nothing had been
            # rewritten, because the keyring still contains the legacy key.
            assert crypto.primary_fernet().decrypt(stored.encode()).decode() == STORED, (
                "the legacy value was never re-encrypted — read-time fallback is not a "
                "migration, and the legacy key can never be retired"
            )
            assert stored != legacy
        finally:
            await eng.dispose()
