"""diagnose() names WHY secrets cannot be read, and refuses to name the wrong cause.

This is the function the shipped en.json:463 sentence was standing in for. That
sentence said "ARSLAN_SECRET_KEY changed" for what was, in the real incident, a salt
change — and a specific, credible, WRONG diagnosis wastes more of someone's time than
no diagnosis, because they go solve a different problem. The whole value of this
function is that its verdicts are DISTINCT and correctly assigned.

Five verdicts, ordered by how actionable and how certain the cause is:

    healthy         nothing stored is unreadable
    secret-missing  unreadable, and the secret is the PUBLIC fallback (no real one set)
    recoverable     unreadable, but a candidate salt opens it — a way back exists
    salt-lost       unreadable, boot regenerated the salt (durable marker), no candidate
    secret-...match unreadable, real secret + adopted salt, nothing opens it, no marker

🔴 THE TEST THAT WOULD HAVE CAUGHT THE MONTH-LONG BUG is
test_salt_lost_is_not_reported_as_secret_missing: real secret, unchanged, ciphertext
written under a salt that is now gone. The verdict must be salt-lost, NOT
secret-missing. The old copy blamed the secret; the salt was the culprit.

The output carries a machine verdict and two counts — no plaintext, no salt bytes. The
frontend localizes the verdict. A diagnosis report that leaked the secrets it is
diagnosing would be a worse fault than the one it describes (same rule as the recovery
probe).
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
LOST_SALT = bytes(range(120, 136))
SECRET_VALUE = "sk-the-value-that-cannot-be-read"


def _fernet(salt: bytes, secret: str = SECRET) -> Fernet:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=crypto._PBKDF2_ITERATIONS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(secret.encode())))


@pytest.fixture
def real_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SECRET_KEY", SECRET)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    import server.config as config

    importlib.reload(config)
    crypto.adopt_salt(CURRENT_SALT, source="test")
    return tmp_path


@pytest.fixture
def no_secret(tmp_path, monkeypatch):
    # The public dev fallback is active (nothing set, no persisted file).
    monkeypatch.delenv("ARSLAN_SECRET_KEY", raising=False)
    monkeypatch.setenv("ARSLAN_SECRET_KEY_FILE", "")
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    import server.config as config

    importlib.reload(config)
    crypto.adopt_salt(CURRENT_SALT, source="test")
    assert crypto.is_insecure_default()
    return tmp_path


async def _db(tmp_path, rows: list[tuple[str, dict]]):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'd.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(migration_runner.apply_pending)
        # A salt row, so diagnose() is not looking at a fresh install.
        await conn.execute(
            sa.text("INSERT INTO settings (key, value) VALUES ('crypto_salt_b64', :s)"),
            {"s": base64.b64encode(CURRENT_SALT).decode()})
        for sql, params in rows:
            await conn.execute(sa.text(sql), params)
    return eng


async def _diagnose(eng) -> dict:
    async with eng.begin() as conn:
        return await conn.run_sync(crypto_boot.diagnose)


async def _snapshot(eng) -> dict:
    async with eng.begin() as conn:
        return dict((await conn.execute(sa.text("SELECT key, value FROM settings"))).all())


class TestHealthy:
    async def test_a_readable_secret_is_healthy(self, real_secret, tmp_path):
        good = crypto.encrypt(SECRET_VALUE)   # under CURRENT_SALT, adopted above
        eng = await _db(tmp_path, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)", {"v": good})])
        try:
            d = await _diagnose(eng)
            assert d["verdict"] == crypto_boot.HEALTHY
            assert d["undecryptable"] == 0
        finally:
            await eng.dispose()

    async def test_an_empty_install_is_healthy(self, real_secret, tmp_path):
        eng = await _db(tmp_path, [])
        try:
            assert (await _diagnose(eng))["verdict"] == crypto_boot.HEALTHY
        finally:
            await eng.dispose()


class TestTheCausesAreDistinguished:
    async def test_no_real_secret_is_secret_missing(self, no_secret, tmp_path):
        orphan = _fernet(LOST_SALT).encrypt(SECRET_VALUE.encode()).decode()
        eng = await _db(tmp_path, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)", {"v": orphan})])
        try:
            d = await _diagnose(eng)
            assert d["verdict"] == crypto_boot.SECRET_MISSING
            assert d["undecryptable"] >= 1
        finally:
            await eng.dispose()

    async def test_salt_lost_is_not_reported_as_secret_missing(self, real_secret, tmp_path):
        # 🔴 THE month-long-bug test. The secret is real and unchanged; the ciphertext
        # was written under a salt that is now gone, and boot recorded that it
        # regenerated the salt (the marker). The verdict must blame the SALT, not the
        # secret — the shipped copy did the opposite.
        orphan = _fernet(LOST_SALT).encrypt(SECRET_VALUE.encode()).decode()
        eng = await _db(tmp_path, [
            ("INSERT INTO settings (key, value) VALUES ('search_api_key', :v)", {"v": orphan}),
            (f"INSERT INTO settings (key, value) VALUES ('{crypto_boot.SALT_LOST_MARKER_KEY}', "
             "'generated-over-existing-ciphertext')", {}),
        ])
        try:
            d = await _diagnose(eng)
            assert d["verdict"] == crypto_boot.SALT_LOST, (
                f"blamed the wrong half: {d['verdict']}"
            )
            assert d["verdict"] != crypto_boot.SECRET_MISSING
        finally:
            await eng.dispose()

    async def test_a_wrong_secret_with_an_intact_salt_is_mismatch(self, real_secret, tmp_path):
        # Real secret, salt row present and adopted, no marker (nothing was
        # regenerated), and nothing opens the value: it was written under a DIFFERENT
        # secret. Distinct from salt-lost precisely by the absent marker.
        written_under_another_secret = _fernet(CURRENT_SALT, secret="some-other-secret") \
            .encrypt(SECRET_VALUE.encode()).decode()
        eng = await _db(tmp_path, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)",
            {"v": written_under_another_secret})])
        try:
            d = await _diagnose(eng)
            assert d["verdict"] == crypto_boot.MISMATCH
        finally:
            await eng.dispose()

    async def test_a_candidate_that_opens_it_is_recoverable(self, real_secret, tmp_path):
        # The old salt file is still sitting in the data dir — a recovery candidate.
        # "recoverable" outranks "salt-lost" even with the marker present, because a
        # way back is the more useful headline.
        orphan = _fernet(LOST_SALT).encrypt(SECRET_VALUE.encode()).decode()
        eng = await _db(tmp_path, [
            ("INSERT INTO settings (key, value) VALUES ('search_api_key', :v)", {"v": orphan}),
            (f"INSERT INTO settings (key, value) VALUES ('{crypto_boot.SALT_LOST_MARKER_KEY}', "
             "'generated-over-existing-ciphertext')", {}),
        ])
        # AFTER the chain, deliberately. Planting it first makes 0039 adopt it as the
        # primary salt — 0039 working correctly — and then the value is not orphaned at
        # all. The real shape is a row already established and an old file turning up
        # later, from a half-restored backup or a copied folder.
        (tmp_path / "crypto_salt").write_bytes(LOST_SALT)
        try:
            d = await _diagnose(eng)
            assert d["verdict"] == crypto_boot.RECOVERABLE
            assert d["recoverable"] >= 1
        finally:
            await eng.dispose()


class TestItLeaksNothingAndWritesNothing:
    async def test_the_diagnosis_carries_no_plaintext_or_salt(self, real_secret, tmp_path):
        orphan = _fernet(LOST_SALT).encrypt(SECRET_VALUE.encode()).decode()
        eng = await _db(tmp_path, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)", {"v": orphan})])
        try:
            d = await _diagnose(eng)
            blob = repr(d)
            assert SECRET_VALUE not in blob
            assert base64.b64encode(CURRENT_SALT).decode() not in blob
            assert CURRENT_SALT.hex() not in blob
        finally:
            await eng.dispose()

    async def test_diagnose_writes_nothing(self, real_secret, tmp_path):
        orphan = _fernet(LOST_SALT).encrypt(SECRET_VALUE.encode()).decode()
        eng = await _db(tmp_path, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)", {"v": orphan})])
        try:
            before = await _snapshot(eng)

            def _guarded(c):
                original = c.exec_driver_sql

                def guarded(sql, *a, **kw):
                    if sql.lstrip()[:6].upper() in ("INSERT", "UPDATE", "DELETE"):
                        raise AssertionError(f"diagnose wrote: {sql[:60]}")
                    return original(sql, *a, **kw)

                c.exec_driver_sql = guarded
                try:
                    return crypto_boot.diagnose(c)
                finally:
                    c.exec_driver_sql = original

            async with eng.begin() as conn:
                await conn.run_sync(_guarded)

            assert await _snapshot(eng) == before
        finally:
            await eng.dispose()


class TestTheVerdictIsAMachineKey:
    async def test_every_verdict_is_from_the_defined_set(self, real_secret, tmp_path):
        eng = await _db(tmp_path, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)",
            {"v": _fernet(LOST_SALT).encrypt(b"x").decode()})])
        try:
            assert (await _diagnose(eng))["verdict"] in crypto_boot.VERDICTS
        finally:
            await eng.dispose()

    def test_the_set_is_small_and_stable(self):
        # A verdict is a machine key the frontend localizes, not a sentence. If this
        # set grows, the frontend copy and its locale files must grow in step, so the
        # count is pinned deliberately rather than left to drift.
        assert crypto_boot.VERDICTS == frozenset({
            crypto_boot.HEALTHY, crypto_boot.SECRET_MISSING, crypto_boot.RECOVERABLE,
            crypto_boot.SALT_LOST, crypto_boot.MISMATCH,
        })


class TestItIsReachableOverHttp:
    """The seam. A diagnosis nobody can fetch is a diagnosis nobody reads.

    Named explicitly because this session has already produced two tests that went
    green on a wrong path, and because `containment` was added to an API response and
    never rendered — reaching the wire is a separate fact from existing.
    """

    async def test_the_endpoint_returns_a_verdict(self, real_secret, tmp_path, monkeypatch):
        import server.db.session as db_session
        from sqlalchemy.ext.asyncio import async_sessionmaker

        monkeypatch.setenv("ARSLAN_API_TOKEN", "")
        eng = await _db(tmp_path, [(
            "INSERT INTO settings (key, value) VALUES ('search_api_key', :v)",
            {"v": _fernet(LOST_SALT).encrypt(SECRET_VALUE.encode()).decode()})])
        maker = async_sessionmaker(eng, expire_on_commit=False)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

        from httpx import ASGITransport, AsyncClient

        from server.main import create_app

        app = create_app()
        app.dependency_overrides[db_session.get_session] = lambda: maker()
        try:
            async with AsyncClient(transport=ASGITransport(app=app),
                                   base_url="http://test") as c:
                r = await c.get("/api/v1/settings/crypto-health")

            assert r.status_code != 404, "endpoint not found — this would prove nothing"
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["verdict"] in crypto_boot.VERDICTS
            assert body["undecryptable"] >= 1
            assert SECRET_VALUE not in r.text
        finally:
            app.dependency_overrides.clear()
            await eng.dispose()
