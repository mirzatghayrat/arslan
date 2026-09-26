"""Read-only credential compatibility for a stopped, restored database.

No key discovery/generation, salt adoption, repair, model call or profile switch.
The trusted caller supplies the original secret in memory, never in CLI args,
and keeps all writers stopped. Only checkpointed standalone databases are read.
"""
from __future__ import annotations

import base64
from contextlib import closing
from pathlib import Path
import sqlite3

from cryptography.fernet import InvalidToken

from server.crypto_material import keyring
from server.services.secret_inventory import CIPHERTEXT_SITES

MAX_CREDENTIALS = 10_000
MAX_TOKEN_BYTES = 1024 * 1024


def check(database: Path, secret: str | None) -> dict:
    if database.is_symlink() or not database.is_file():
        return {"status": "preflight_unavailable", "checked": 0, "unreadable": 0}
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            return {"status": "preflight_unavailable", "checked": 0, "unreadable": 0}
    try:
        # immutable avoids SQLite creating WAL/SHM files even for a WAL-mode
        # snapshot. Never use it on an active database or ignore pending journals.
        with closing(sqlite3.connect(f"{database.absolute().as_uri()}?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            return _check(db, secret)
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return {"status": "preflight_unavailable", "checked": 0, "unreadable": 0}


def _check(db, secret):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    salt = None
    if "settings" in tables:
        row = db.execute("SELECT substr(value,1,4097) FROM settings WHERE key='crypto_salt_b64'").fetchone()
        if row and row[0]:
            try:
                if not isinstance(row[0], str) or len(row[0]) > 4096:
                    raise ValueError
                salt = base64.b64decode(row[0], validate=True)
                if len(salt) < 16:
                    raise ValueError
            except (ValueError, TypeError):
                return {"status": "invalid_salt", "checked": 0, "unreadable": 0}
    effective = (secret or "").strip()
    # Do not guess the public fallback secret, a file salt, or a recovery salt.
    keys = keyring(effective, salt) if effective else None
    checked = unreadable = 0
    for table, column, where in CIPHERTEXT_SITES:
        if table not in tables:
            continue
        sql = (f"SELECT substr({column},1,?), length({column}), typeof({column}) FROM {table} "
               f"WHERE {column} IS NOT NULL AND {column} != ''")
        if where:
            sql += f" AND ({where})"
        for token, length, kind in db.execute(sql, (MAX_TOKEN_BYTES + 1,)):
            checked += 1
            if checked > MAX_CREDENTIALS:
                return {"status": "credential_limit", "checked": checked - 1, "unreadable": unreadable}
            if kind != "text" or length > MAX_TOKEN_BYTES:
                unreadable += 1
                continue
            if keys is not None:
                try:
                    # Also require the UTF-8 representation consumed by normal reads.
                    keys.decrypt(token.encode("utf-8")).decode("utf-8")
                except (InvalidToken, UnicodeError, ValueError):
                    unreadable += 1
    status = ("no_stored_credentials" if not checked else "secret_required" if not effective
              else "unreadable_credentials" if unreadable else "compatible")
    return {"status": status, "checked": checked, "unreadable": unreadable}
