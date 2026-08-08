"""Group B: candidate salts are TRIED and REPORTED. Nothing is written.

THE SPLIT. A write after a successful decryption is a migration; a write before one is
a gamble. Group A — keys legitimately derived from the current inputs — migrates itself
at boot, ungated, because gating it would keep the legacy format alive forever. Group B
is the other half: salts we went LOOKING for, in files that may or may not be the right
ones. Even when a candidate opens a value, the rewrite waits for a person.

The user's words for the boundary: "not one byte before we nod."

🔴 WHY "IT WROTE NOTHING" IS THE HARD PART TO TEST. It is the assertion most easily
satisfied by accident — a function that does nothing at all passes it. So this file
pairs every read-only assertion with a positive one: the probe must also FIND the
recoverable value and name which candidate opened it. A pass therefore requires both
"reported something true" and "changed nothing", and neither alone is enough.

AND THE REPORT MUST NOT CARRY PLAINTEXT. It goes to a log and to a screen. A recovery
report that leaks the very secrets it is reporting about would be a worse defect than
the one being fixed, so the probe returns locations and candidate labels only, and one
test below reads the whole report looking for the secret.
"""
from __future__ import annotations

import base64
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
CURRENT_SALT = bytes(range(70, 86))
LOST_SALT = bytes(range(90, 106))          # the one the ciphertext was written under
SECRET_VALUE = "sk-the-one-that-went-missing"


def _fernet_for(salt: bytes) -> Fernet:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=crypto._PBKDF2_ITERATIONS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(SECRET.encode())))


@pytest.fixture
def install(tmp_path, monkeypatch):
    """A database holding one secret written under a salt nobody has any more."""
    monkeypatch.setenv("ARSLAN_SECRET_KEY", SECRET)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    import server.config as config

    importlib.reload(config)
    crypto.adopt_salt(CURRENT_SALT, source="test")
    return tmp_path


async def _db_with_orphan(install) -> tuple:
    db = install / "orphan.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db}")
    orphan = _fernet_for(LOST_SALT).encrypt(SECRET_VALUE.encode()).decode()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(migration_runner.apply_pending)
        await conn.execute(
            sa.text("INSERT INTO settings (key, value) VALUES "
                    "(:k, :v), ('crypto_salt_b64', :s)"),
            {"k": "search_api_key", "v": orphan,
             "s": base64.b64encode(CURRENT_SALT).decode()},
        )
    return eng, orphan


async def _snapshot(eng) -> dict:
    async with eng.begin() as conn:
        return dict((await conn.execute(sa.text("SELECT key, value FROM settings"))).all())


class TestTheProbeFindsAndReportsWithoutWriting:
    async def test_it_names_the_candidate_that_opened_the_value(self, install):
        eng, _ = await _db_with_orphan(install)
        try:
            before = await _snapshot(eng)

            async with eng.begin() as conn:
                report = await conn.run_sync(
                    lambda c: crypto_boot.probe_recovery_candidates(c, extra_salts=(
                        ("a-salt-i-found", LOST_SALT),)))

            # Positive half: it actually found the thing.
            assert report["recoverable"] == 1
            assert report["unreachable"] == 0
            found = report["findings"][0]
            assert found["table"] == "settings" and found["ident"] == "search_api_key"
            assert found["candidate"] == "a-salt-i-found"

            # Read-only half. Paired with the above so a do-nothing implementation
            # cannot pass by being inert.
            assert await _snapshot(eng) == before
        finally:
            await eng.dispose()

    async def test_the_report_carries_no_plaintext(self, install):
        eng, _ = await _db_with_orphan(install)
        try:
            async with eng.begin() as conn:
                report = await conn.run_sync(
                    lambda c: crypto_boot.probe_recovery_candidates(c, extra_salts=(
                        ("a-salt-i-found", LOST_SALT),)))

            assert SECRET_VALUE not in repr(report), "the report leaks the secret it found"
        finally:
            await eng.dispose()

    async def test_a_value_no_candidate_opens_is_reported_as_unreachable(self, install):
        eng, _ = await _db_with_orphan(install)
        try:
            async with eng.begin() as conn:
                report = await conn.run_sync(
                    lambda c: crypto_boot.probe_recovery_candidates(c, extra_salts=()))

            assert report["recoverable"] == 0
            assert report["unreachable"] == 1
        finally:
            await eng.dispose()

    async def test_values_the_current_key_opens_are_not_in_the_report_at_all(self, install):
        # Group A's territory. Listing them would turn a healthy install's report into
        # a wall of rows and bury the one line that matters.
        eng, _ = await _db_with_orphan(install)
        try:
            async with eng.begin() as conn:
                await conn.execute(
                    sa.text("INSERT INTO settings (key, value) VALUES ('github_token', :v)"),
                    {"v": crypto.encrypt("ghp-fine")})
                report = await conn.run_sync(
                    lambda c: crypto_boot.probe_recovery_candidates(c, extra_salts=()))

            idents = {f["ident"] for f in report["findings"]}
            assert "github_token" not in idents
        finally:
            await eng.dispose()

    async def test_it_writes_nothing_even_when_every_write_would_raise(self, install):
        # The direct form of the rule, rather than a before/after comparison: any
        # attempt to write at all blows up. Catches a write that happens to be a no-op
        # on this particular fixture.
        eng, _ = await _db_with_orphan(install)
        try:
            def _probe(c):
                original = c.exec_driver_sql

                def guarded(sql, *a, **kw):
                    if sql.lstrip()[:6].upper() in ("INSERT", "UPDATE", "DELETE"):
                        raise AssertionError(f"the recovery probe wrote: {sql[:60]}")
                    return original(sql, *a, **kw)

                c.exec_driver_sql = guarded
                try:
                    return crypto_boot.probe_recovery_candidates(
                        c, extra_salts=(("a-salt-i-found", LOST_SALT),))
                finally:
                    c.exec_driver_sql = original

            async with eng.begin() as conn:
                report = await conn.run_sync(_probe)

            assert report["recoverable"] == 1   # still did its job under the guard
        finally:
            await eng.dispose()


class TestTheFallbackConstantIsATriedCandidate:
    async def test_ciphertext_written_under_the_fallback_salt_is_recoverable(self, install):
        # The third silent channel: <data_dir> unreadable once meant deriving from a
        # fixed public constant. Installs really did write under it, and keeping it as
        # a candidate is the only way back for them.
        db = install / "fb.db"
        eng = create_async_engine(f"sqlite+aiosqlite:///{db}")
        token = _fernet_for(crypto._FALLBACK_SALT).encrypt(b"sk-under-fallback").decode()
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(migration_runner.apply_pending)
            await conn.execute(
                sa.text("INSERT INTO settings (key, value) VALUES "
                        "('search_api_key', :v), ('crypto_salt_b64', :s)"),
                {"v": token, "s": base64.b64encode(CURRENT_SALT).decode()})
        try:
            async with eng.begin() as conn:
                report = await conn.run_sync(
                    lambda c: crypto_boot.probe_recovery_candidates(c, extra_salts=()))

            assert report["recoverable"] == 1
            assert report["findings"][0]["candidate"] == "fallback-salt-constant"
        finally:
            await eng.dispose()

    async def test_a_stale_salt_file_beside_the_database_is_a_candidate(self, install):
        # After 0039 the file is inert for derivation, but if it holds a DIFFERENT salt
        # from the row, it is exactly the kind of thing worth trying.
        #
        # ORDER MATTERS HERE, and getting it wrong is instructive: planting the file
        # BEFORE the migration chain makes 0039 adopt it as the primary salt — which is
        # 0039 working correctly, and leaves no stale file to find. The state this test
        # is about is the reverse one: a row already established, and a file from some
        # older data dir arriving afterwards (a half-restored backup, a copied folder).
        eng, _ = await _db_with_orphan(install)
        (install / "crypto_salt").write_bytes(LOST_SALT)
        try:
            async with eng.begin() as conn:
                report = await conn.run_sync(
                    lambda c: crypto_boot.probe_recovery_candidates(c, extra_salts=()))

            assert report["recoverable"] == 1
            assert report["findings"][0]["candidate"] == "data-dir-salt-file"
        finally:
            await eng.dispose()


class TestTheGatedRekeyIsSeparateAndExplicit:
    async def test_it_is_not_called_during_boot(self, install):
        # Structural: boot wires resolve_and_adopt_salt and migrate_legacy_ciphertext.
        # If recover_with_salt ever appears there, the human gate is gone.
        eng, orphan = await _db_with_orphan(install)
        try:
            async with eng.begin() as conn:
                await conn.run_sync(crypto_boot.resolve_and_adopt_salt)
                await conn.run_sync(crypto_boot.migrate_legacy_ciphertext)

            assert (await _snapshot(eng))["search_api_key"] == orphan, (
                "boot rewrote a group-B value; the gate is not holding"
            )
        finally:
            await eng.dispose()

    async def test_when_called_explicitly_it_rekeys_and_verifies(self, install):
        eng, orphan = await _db_with_orphan(install)
        try:
            async with eng.begin() as conn:
                moved = await conn.run_sync(
                    lambda c: crypto_boot.recover_with_salt(c, LOST_SALT))

            assert moved == 1
            stored = (await _snapshot(eng))["search_api_key"]
            assert stored != orphan
            # Judged by the CURRENT key alone — the whole point is that it no longer
            # depends on a salt nobody has.
            assert _fernet_for(CURRENT_SALT).decrypt(stored.encode()).decode() == SECRET_VALUE
        finally:
            await eng.dispose()

    async def test_a_wrong_salt_moves_nothing(self, install):
        eng, orphan = await _db_with_orphan(install)
        try:
            async with eng.begin() as conn:
                moved = await conn.run_sync(
                    lambda c: crypto_boot.recover_with_salt(c, bytes(range(16))))

            assert moved == 0
            assert (await _snapshot(eng))["search_api_key"] == orphan
        finally:
            await eng.dispose()


class TestRecoveryIsVerifiedBeforeItCounts:
    """The mirror of the group-A verification test.

    Added because a mutation removing the read-back check survived — the third time
    this round that a branch I wrote had no test on it (the corrupt salt row, the
    false-alarm fix, and now this). Predicting the hole is not the same as closing it.

    Recovery is the more dangerous of the two rewrites: group A rewrites values the
    current key already opens, so a botched write loses nothing that was not already
    reachable. Here the ORIGINAL is the only copy of something the current key cannot
    open. Writing something unreadable over it is the one way this feature could
    destroy what it exists to rescue.
    """

    async def test_a_recovery_that_does_not_read_back_raises_and_keeps_the_original(
        self, install, monkeypatch
    ):
        eng, orphan = await _db_with_orphan(install)
        try:
            monkeypatch.setattr(crypto, "encrypt", lambda _p: "gAAAAAcorrupted")

            with pytest.raises(crypto_boot.MigrationVerificationError):
                async with eng.begin() as conn:
                    await conn.run_sync(lambda c: crypto_boot.recover_with_salt(c, LOST_SALT))

            monkeypatch.undo()
            # Rolled back: the only copy of the unreachable secret is still there, and
            # the candidate salt still opens it.
            stored = (await _snapshot(eng))["search_api_key"]
            assert stored == orphan, "recovery destroyed the value it was rescuing"
            assert _fernet_for(LOST_SALT).decrypt(stored.encode()).decode() == SECRET_VALUE
        finally:
            await eng.dispose()
