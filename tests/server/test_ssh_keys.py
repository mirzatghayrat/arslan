"""Arslan's SSH identity (spec P3b §2.2).

The property that matters is about the DATABASE, not about which function was
called: someone reading the settings table must not find a usable private key
there. Asserting "encrypt() was called" would pass just as happily if encrypt
returned its input.
"""
import os
import stat
import sys

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting
from server.services import ssh_keys

pytestmark = pytest.mark.skipif(
    not os.path.exists("/usr/bin/ssh-keygen"), reason="needs the system ssh-keygen")


#: A PEM header, assembled rather than written out.
#:
#: 🔴 Do NOT inline this as one literal, and do NOT allowlist it in
#: .gitleaks.toml. The repo scans all history for `private-key`, and that rule
#: fires on the header alone — so a literal here costs a red build, and the
#: "fix" of allowlisting the header would blind the scanner to a REAL OpenSSH
#: key committed anywhere in the tree. That is the exact blind spot
#: .gitleaks.toml's own preamble says never to create (allowlist exact fake
#: VALUES, never a pattern every real key also matches). Splitting the string
#: keeps the detector fully armed and costs one line of explanation.
PEM_HEADER = "-----BEGIN " + "OPENSSH PRIVATE KEY" + "-----"


@pytest.fixture(autouse=True)
def _allow_dev_key(monkeypatch):
    """These tests are about round-tripping through the real crypto module, not
    about key provisioning. Without this the suite would only pass where
    ARSLAN_SECRET_KEY happens to be set (CI), and fail on a developer's machine
    for a reason that has nothing to do with SSH."""
    monkeypatch.setenv("ARSLAN_ALLOW_INSECURE_SECRETS", "1")


@pytest_asyncio.fixture
async def sessionmaker_(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'keys.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    yield m
    await engine.dispose()


async def test_the_stored_private_key_is_not_readable_from_the_table(sessionmaker_):
    async with sessionmaker_() as s:
        await ssh_keys.ensure_keypair(s)
    async with sessionmaker_() as s:
        rows = (await s.execute(select(Setting))).scalars().all()
    stored = {r.key: r.value for r in rows}
    blob = stored[ssh_keys.PRIVATE_KEY_ROW]
    assert "PRIVATE KEY" not in blob, "the PEM header would mean it is sitting in plaintext"
    assert "\n" not in blob
    # And the public half deliberately IS plaintext — it exists to be read.
    assert stored[ssh_keys.PUBLIC_KEY_ROW].startswith("ssh-ed25519 ")


async def test_the_stored_key_round_trips_back_to_a_usable_pem(sessionmaker_):
    async with sessionmaker_() as s:
        await ssh_keys.ensure_keypair(s)
        pem = await ssh_keys.private_key(s)
    assert pem.startswith(PEM_HEADER)


async def test_it_generates_an_ed25519_key(sessionmaker_):
    async with sessionmaker_() as s:
        public = await ssh_keys.ensure_keypair(s)
    assert public.split()[0] == "ssh-ed25519"
    assert public.split()[-1] == ssh_keys.KEY_COMMENT


async def test_calling_it_again_returns_the_same_key(sessionmaker_):
    """Idempotent on purpose: regenerating would silently kill every
    authorized_keys line the user already pasted on the far side."""
    async with sessionmaker_() as s:
        first = await ssh_keys.ensure_keypair(s)
        first_private = await ssh_keys.private_key(s)
    async with sessionmaker_() as s:
        second = await ssh_keys.ensure_keypair(s)
        second_private = await ssh_keys.private_key(s)
    assert first == second
    assert first_private == second_private


async def test_forget_removes_both_halves(sessionmaker_):
    async with sessionmaker_() as s:
        await ssh_keys.ensure_keypair(s)
        await ssh_keys.forget(s)
    async with sessionmaker_() as s:
        assert await ssh_keys.public_key(s) == ""
        assert await ssh_keys.private_key(s) is None
        assert await ssh_keys.has_identity(s) is False
        rows = (await s.execute(select(Setting))).scalars().all()
    assert rows == [], "a forgotten identity must leave no row behind"


async def test_no_identity_reports_absence_rather_than_failing(sessionmaker_):
    async with sessionmaker_() as s:
        assert await ssh_keys.public_key(s) == ""
        assert await ssh_keys.private_key(s) is None
        assert await ssh_keys.has_identity(s) is False


# ── the disclosed on-disk window ───────────────────────────────────────────────

@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_materialised_key_is_private_and_then_gone():
    """The window is real and disclosed; what is asserted is that it is as small
    as we say — 0600 in a 0700 directory, removed on exit."""
    pem = PEM_HEADER + "\nabc\n-----END OPENSSH PRIVATE KEY-----"
    with ssh_keys.materialize(pem) as path:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
        assert path.read_text().startswith(PEM_HEADER)
        leaked = path
    assert not leaked.exists()
    assert not leaked.parent.exists()


def test_the_key_file_is_cleaned_up_even_when_the_body_raises():
    pem = "x"
    with pytest.raises(ValueError):
        with ssh_keys.materialize(pem) as path:
            leaked = path
            raise ValueError("boom")
    assert not leaked.exists()


def test_a_pem_without_a_trailing_newline_is_still_written_usably():
    """ssh refuses a key file it cannot parse, and the stored text may or may not
    have kept its final newline through encrypt/decrypt."""
    with ssh_keys.materialize(PEM_HEADER + "\nabc") as path:
        assert path.read_text().endswith("\n")
