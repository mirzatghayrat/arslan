"""Group A: ciphertext the CURRENT inputs can already open is re-encrypted at boot.

THE SPLIT THIS IMPLEMENTS. A write that follows a successful decryption is a
migration; a write that precedes one is a gamble. The keyring is therefore in two
halves, and that seam is the gate:

  group A — keys legitimately derived from the current inputs:
              PBKDF2(secret, DB salt)   the primary; nothing to do
              SHA256(secret)            legacy, unsalted, pre-d6d8afa8
            → re-encrypted automatically at boot, no gate.

  group B — keys we went looking for (a salt file found elsewhere, the fallback
            constant) → report only, writing needs a human. NOT in this commit.

WHY GROUP A IS NOT GATED. d6d8afa8 added read-time fallback to the legacy key and
called that a migration. It was not: the ciphertext was never rewritten, so the
legacy key could never be retired, and the next change of keyring lost it for good.
Putting a human gate in front of THIS half would reproduce that exactly — the legacy
format made immortal by caution.

🔴 HOW THESE TESTS AVOID BEING FOOLED. "The value still decrypts after boot" is true
of a migration AND of doing nothing at all, because read-time fallback also decrypts
it. So the judge is: remove the legacy key from the keyring, and check it STILL
opens. Only an actual rewrite survives that. Every test below that claims a migration
happened uses that judge, not the weaker one.
"""
from __future__ import annotations

import base64
import hashlib
import importlib

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine

from server import crypto
from server.db.migrations import runner as migration_runner
from server.db.models import Base
from server.services import crypto_boot

SECRET = "a-real-strong-random-key-0123456789"
SALT = bytes(range(50, 66))


def _legacy_token(plaintext: str) -> str:
    """Ciphertext exactly as the pre-d6d8afa8 build wrote it: bare SHA256, no salt."""
    key = base64.urlsafe_b64encode(hashlib.sha256(SECRET.encode()).digest())
    return Fernet(key).encrypt(plaintext.encode()).decode()


def _primary_only_fernet() -> Fernet:
    """The primary key ALONE — the judge. No legacy fallback to hide behind."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=crypto.current_salt(),
                     iterations=crypto._PBKDF2_ITERATIONS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(SECRET.encode())))


@pytest.fixture
def booted(tmp_path, monkeypatch):
    """A real database with the salt installed, ready to be swept."""
    monkeypatch.setenv("ARSLAN_SECRET_KEY", SECRET)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    import server.config as config

    importlib.reload(config)
    crypto.adopt_salt(SALT, source="test")
    return tmp_path / "mig.db"


async def _prepare(db, seed_sql: list[tuple[str, dict]]):
    eng = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(migration_runner.apply_pending)
        for sql, params in seed_sql:
            await conn.execute(sa.text(sql), params)
    return eng


async def _sweep(eng) -> int:
    async with eng.begin() as conn:
        await conn.run_sync(crypto_boot.resolve_and_adopt_salt)
        return await conn.run_sync(crypto_boot.migrate_legacy_ciphertext)


async def _value(eng, sql, params=None) -> str:
    async with eng.begin() as conn:
        return (await conn.execute(sa.text(sql), params or {})).scalar()


class TestLegacyIsActuallyRewritten:
    async def test_a_settings_secret_is_migrated(self, booted):
        eng = await _prepare(booted, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)",
            {"v": _legacy_token("sk-from-2026-07")},
        )])
        try:
            count = await _sweep(eng)
            stored = await _value(
                eng, "SELECT value FROM settings WHERE key = 'search_api_key'")

            assert count == 1
            # THE judge: the primary key ALONE must open it. "crypto.decrypt works"
            # would also pass on a build that migrated nothing, because read-time
            # fallback opens the legacy token too.
            assert _primary_only_fernet().decrypt(stored.encode()).decode() == "sk-from-2026-07"
        finally:
            await eng.dispose()

    async def test_a_provider_key_and_an_mcp_env_are_migrated_too(self, booted):
        eng = await _prepare(booted, [
            ("INSERT INTO provider_configs (id, label, provider, model, api_key, is_primary) "
             "VALUES (1, 'x', 'deepseek', 'deepseek-chat', :v, 1)",
             {"v": _legacy_token("sk-provider")}),
            # Every NOT NULL column spelled out: the ORM defaults do not apply to raw
            # SQL, and this seed exists to exercise the sweep, not the schema.
            ("INSERT INTO mcp_servers (id, label, command, args, transport, status, env) "
             "VALUES (1, 'm', 'echo', '[]', 'stdio', 'registered', :v)",
             {"v": _legacy_token('{"BRAVE_API_KEY": "bsk-1"}')}),
        ])
        try:
            count = await _sweep(eng)

            assert count == 2, "a storage point was not swept"
            pk = await _value(eng, "SELECT api_key FROM provider_configs WHERE id = 1")
            env = await _value(eng, "SELECT env FROM mcp_servers WHERE id = 1")
            assert _primary_only_fernet().decrypt(pk.encode()).decode() == "sk-provider"
            assert "bsk-1" in _primary_only_fernet().decrypt(env.encode()).decode()
        finally:
            await eng.dispose()

    async def test_the_second_boot_has_nothing_left_to_do(self, booted):
        # Proves the rewrite LANDED rather than being redone from fallback each boot.
        eng = await _prepare(booted, [(
            "INSERT INTO settings (key, value) VALUES ('github_token', :v)",
            {"v": _legacy_token("ghp-abc")},
        )])
        try:
            assert await _sweep(eng) == 1
            assert await _sweep(eng) == 0
        finally:
            await eng.dispose()


class TestItLeavesEverythingElseAlone:
    async def test_already_primary_values_are_untouched(self, booted):
        eng = await _prepare(booted, [])
        try:
            async with eng.begin() as conn:
                await conn.run_sync(crypto_boot.resolve_and_adopt_salt)
            token = crypto.encrypt("sk-already-current")
            async with eng.begin() as conn:
                await conn.execute(
                    sa.text("INSERT INTO settings (key, value) VALUES ('llm_api_key', :v)"),
                    {"v": token})

            count = await _sweep(eng)

            assert count == 0
            assert await _value(
                eng, "SELECT value FROM settings WHERE key = 'llm_api_key'") == token
        finally:
            await eng.dispose()

    async def test_group_B_ciphertext_is_left_for_a_human(self, booted):
        # Encrypted under a salt we do not hold. Neither group-A key opens it, and the
        # sweep must NOT touch it: rewriting what it cannot read would be the gamble
        # the split exists to forbid, and the row is still a recovery candidate.
        other = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"someone-elses").digest()))
        opaque = other.encrypt(b"sk-unreachable").decode()
        eng = await _prepare(booted, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)",
            {"v": opaque},
        )])
        try:
            count = await _sweep(eng)

            assert count == 0
            assert await _value(
                eng, "SELECT value FROM settings WHERE key = 'search_api_key'") == opaque
        finally:
            await eng.dispose()

    async def test_an_empty_value_is_not_a_migration_candidate(self, booted):
        eng = await _prepare(booted, [(
            "INSERT INTO settings (key, value) VALUES ('github_token', '')", {},
        )])
        try:
            assert await _sweep(eng) == 0
        finally:
            await eng.dispose()


class TestTheRewriteIsVerifiedBeforeItCounts:
    async def test_a_row_that_fails_read_back_is_not_counted_or_left_broken(
        self, booted, monkeypatch
    ):
        # Write-then-read-back is the difference between "we wrote something" and "we
        # wrote something that opens". Simulate a corrupting write and require the
        # sweep to refuse it rather than report success.
        eng = await _prepare(booted, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)",
            {"v": _legacy_token("sk-precious")},
        )])
        try:
            monkeypatch.setattr(crypto, "encrypt", lambda _p: "gAAAAAcorrupted")

            # Narrow on purpose. An earlier draft used pytest.raises(Exception) and
            # PASSED before migrate_legacy_ciphertext existed at all — the AttributeError
            # satisfied it. A test that green-lights the absence of the feature it tests
            # is worse than no test.
            with pytest.raises(crypto_boot.MigrationVerificationError):
                await _sweep(eng)

            # The transaction rolled back: the original is still there and still opens.
            monkeypatch.undo()
            stored = await _value(
                eng, "SELECT value FROM settings WHERE key = 'search_api_key'")
            assert crypto.decrypt(stored) == "sk-precious", "the original was destroyed"
        finally:
            await eng.dispose()


class TestAPreD6d8afa8InstallIsNotCalledDataLoss:
    """The most ordinary upgrade there is, and it was briefly reported as data loss.

    An install predating d6d8afa8 stores unsalted, bare-SHA256 ciphertext and has no
    salt file at all. It therefore arrives at boot with rows present and no salt row —
    which the first version of the resolver read as "the salt was lost", logged as an
    ERROR, and recorded in a durable marker. Nothing was lost: the legacy key opens
    every one of those values, and the sweep re-encrypts them seconds later.

    🔴 I found that by reading a log line during a red run and fixed it WITHOUT a
    regression test; a mutation reverting the fix stayed green. So this exists.

    A false data-loss alarm is not the cautious direction. It teaches its reader to
    skip the message, which costs precisely the one time it is real — and the person
    this whole spec is for spent a month on a wrong diagnosis.
    """

    async def test_it_is_migrated_and_not_marked(self, booted):
        eng = await _prepare(booted, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)",
            {"v": _legacy_token("sk-since-forever")},
        )])
        try:
            async with eng.begin() as conn:
                provenance = await conn.run_sync(crypto_boot.resolve_and_adopt_salt)
                count = await conn.run_sync(crypto_boot.migrate_legacy_ciphertext)

            assert provenance == crypto_boot.GENERATED_FRESH, (
                "a legacy install was treated as having lost its salt"
            )
            async with eng.begin() as conn:
                keys = {r[0] for r in (await conn.execute(
                    sa.text("SELECT key FROM settings"))).all()}
            assert crypto_boot.SALT_LOST_MARKER_KEY not in keys, "false data-loss alarm"

            # ...and the value really did move, judged by the primary key alone.
            assert count == 1
            stored = await _value(
                eng, "SELECT value FROM settings WHERE key = 'search_api_key'")
            assert _primary_only_fernet().decrypt(stored.encode()).decode() == "sk-since-forever"
        finally:
            await eng.dispose()

    async def test_a_genuinely_unreachable_value_IS_still_marked(self, booted):
        # The other side: the fix must not have turned the alarm off entirely.
        other = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"a-lost-salt").digest()))
        eng = await _prepare(booted, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)",
            {"v": other.encrypt(b"sk-gone").decode()},
        )])
        try:
            async with eng.begin() as conn:
                provenance = await conn.run_sync(crypto_boot.resolve_and_adopt_salt)

            assert provenance == crypto_boot.GENERATED_OVER_CIPHERTEXT
        finally:
            await eng.dispose()
