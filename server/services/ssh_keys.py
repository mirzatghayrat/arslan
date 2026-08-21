"""Arslan's own SSH identity (spec P3b §2.2).

One ed25519 keypair, generated on first use. The private key lives encrypted in
the settings table; the public key is plaintext because its whole purpose is to
be shown and pasted into a remote `authorized_keys`.

These rows are deliberately NOT settings. They are not in `_PLAIN_KEYS` or
`_SECRET_KEYS`, `SettingsIn` does not accept them, and the settings PUT path
cannot reach them — a generated identity is not something a client should be
able to overwrite by echoing back a GET body (that failure mode has bitten this
codebase before).

🔴 Honest boundary, and it must stay in the UI copy too: `materialize()` puts the
DECRYPTED private key on local disk for the lifetime of one command. `ssh -i`
takes a path and nothing else; whether `/dev/fd/N` could avoid the file is
UNVERIFIED and is not a design assumption here. What is actually guaranteed:
the directory is 0700, the file is 0600, both are created by this process, and
both are removed when the command returns. Do not write "the private key never
touches disk" anywhere.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import stat
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from server import crypto
from server.db.models import Setting

logger = logging.getLogger(__name__)

PRIVATE_KEY_ROW = "_ssh_identity_private"
PUBLIC_KEY_ROW = "_ssh_identity_public"

_SSH_KEYGEN = "/usr/bin/ssh-keygen"
_KEYGEN_TIMEOUT_S = 20.0

#: What the generated key is labelled with on the remote side, so a person
#: reading their own authorized_keys can tell where the line came from.
KEY_COMMENT = "arslan"


async def _row(session: AsyncSession, key: str) -> str | None:
    row = await session.get(Setting, key)
    return row.value if row else None


async def _store(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


async def public_key(session: AsyncSession) -> str:
    """The public key to show the user, or "" when no identity exists yet."""
    return (await _row(session, PUBLIC_KEY_ROW)) or ""


async def has_identity(session: AsyncSession) -> bool:
    return bool(await _row(session, PRIVATE_KEY_ROW))


async def _generate() -> tuple[str, str]:
    """Run ssh-keygen in a scratch dir and return (private_pem, public_line)."""
    tmp = Path(tempfile.mkdtemp(prefix="arslan-keygen-"))
    try:
        target = tmp / "id_ed25519"
        proc = await asyncio.create_subprocess_exec(
            _SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", KEY_COMMENT,
            "-f", str(target),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout=_KEYGEN_TIMEOUT_S)
        if proc.returncode != 0 or not target.exists():
            raise RuntimeError(f"ssh-keygen failed: {err.decode('utf-8', 'replace')[:200]}")
        return target.read_text(), (tmp / "id_ed25519.pub").read_text().strip()
    finally:
        _wipe(tmp)


async def ensure_keypair(session: AsyncSession) -> str:
    """Return the public key, generating the identity on first call.

    Idempotent: an existing private key is never regenerated, because rotating it
    would silently invalidate every authorized_keys line the user already pasted.
    """
    existing_pub = await _row(session, PUBLIC_KEY_ROW)
    if await _row(session, PRIVATE_KEY_ROW) and existing_pub:
        return existing_pub
    private, public = await _generate()
    await _store(session, PRIVATE_KEY_ROW, crypto.encrypt(private))
    await _store(session, PUBLIC_KEY_ROW, public)
    await session.commit()
    return public


async def private_key(session: AsyncSession) -> str | None:
    """The decrypted private key, or None when there is no identity yet."""
    enc = await _row(session, PRIVATE_KEY_ROW)
    if not enc:
        return None
    return crypto.decrypt(enc)


async def forget(session: AsyncSession) -> None:
    """Drop the identity entirely. Every authorized_keys line for it goes dead."""
    for key in (PRIVATE_KEY_ROW, PUBLIC_KEY_ROW):
        row = await session.get(Setting, key)
        if row:
            await session.delete(row)
    await session.commit()


def _wipe(path: Path) -> None:
    """Remove a scratch tree, best effort — a leftover 0600 key file is the one
    piece of debris that actually matters, so failures are logged, not swallowed
    silently."""
    import shutil
    try:
        shutil.rmtree(path)
    except OSError:            # pragma: no cover - filesystem-dependent
        logger.warning("ssh_keys: could not remove scratch dir %s", path)


@contextlib.contextmanager
def materialize(private_pem: str):
    """Yield a Path to the private key on disk, 0600 inside a 0700 dir, removed on exit.

    See the module docstring: this window is real and is disclosed, not hidden.
    """
    tmp = Path(tempfile.mkdtemp(prefix="arslan-ssh-"))
    os.chmod(tmp, stat.S_IRWXU)
    key_path = tmp / "id_ed25519"
    # Create with 0600 from the outset rather than chmod-after: a world-readable
    # instant, however short, is a window that does not need to exist.
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(private_pem if private_pem.endswith("\n") else private_pem + "\n")
        yield key_path
    finally:
        _wipe(tmp)
