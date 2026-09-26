"""Offline candidate-only credential adaptation; not an approval/UI boundary.

The trusted coordinator must establish a durable target key and explicit consent.
No configuration, key discovery, normal boot, profile activation or network work.
Parents must be trusted and older/uncooperative writers stopped by the caller.
"""
from __future__ import annotations

import base64
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from server.crypto_material import keyring
from server.services.data_profile_lock import hold
from server.services.recovery_preflight import MAX_CREDENTIALS, MAX_TOKEN_BYTES
from server.services.secret_inventory import CIPHERTEXT_SITES

MAX_TOTAL_TOKENS = 16 * 1024 * 1024


def _secret(value):
    if not isinstance(value, str) or not value.strip() or '\0' in value or len(value.encode()) > 8192:
        raise ValueError('recovery_rewrap_refused')
    return value.strip()


def _directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('recovery_rewrap_refused')
    return info.st_dev, info.st_ino


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid, info.st_nlink)


def _rewrite(db, source, target):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    salt = None
    if 'settings' in tables:
        rows = db.execute("SELECT substr(value,1,4097), typeof(value) FROM settings "
                          "WHERE key='crypto_salt_b64' LIMIT 2").fetchall()
        if len(rows) > 1:
            raise ValueError('recovery_rewrap_refused')
        if rows and rows[0][0]:
            value, kind = rows[0]
            if kind != 'text' or len(value) > 4096:
                raise ValueError('recovery_rewrap_refused')
            salt = base64.b64decode(value, validate=True)
            if len(salt) < 16:
                raise ValueError('recovery_rewrap_refused')
    old, new = keyring(source, salt), keyring(target, salt)
    replacements = []
    total = 0
    for table, column, where in CIPHERTEXT_SITES:
        if table not in tables:
            # A view with an inventory name must not be silently skipped.
            if db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
                raise ValueError('recovery_rewrap_refused')
            continue
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchone():
            raise ValueError('recovery_rewrap_refused')
        ident = 'key' if table == 'settings' else 'id'
        sql = (f'SELECT {ident}, substr({column},1,?), length({column}), typeof({column}) '
               f'FROM {table} WHERE {column} IS NOT NULL AND {column} != \'\'')
        if where:
            sql += f' AND ({where})'
        seen = set()
        for identity, token, length, kind in db.execute(sql, (MAX_TOKEN_BYTES + 1,)):
            if (identity is None or identity in seen or kind != 'text' or length > MAX_TOKEN_BYTES
                    or len(replacements) >= MAX_CREDENTIALS):
                raise ValueError('recovery_rewrap_refused')
            seen.add(identity)
            total += len(token.encode())
            if total > MAX_TOTAL_TOKENS:
                raise ValueError('recovery_rewrap_refused')
            plaintext = old.decrypt(token.encode())
            plaintext.decode('utf-8')
            replacement = new.encrypt(plaintext).decode()
            if new.decrypt(replacement.encode()) != plaintext:
                raise ValueError('recovery_rewrap_refused')
            replacements.append((table, column, ident, identity, replacement, plaintext))
    # All source values must open before the first rewrite. Staged writes are
    # additionally transactional and verified from SQLite, not just in memory.
    for table, column, ident, identity, replacement, plaintext in replacements:
        changed = db.execute(f'UPDATE {table} SET {column}=? WHERE {ident}=?', (replacement, identity))
        if changed.rowcount != 1:
            raise ValueError('recovery_rewrap_refused')
        actual = db.execute(f'SELECT {column} FROM {table} WHERE {ident}=?', (identity,)).fetchone()[0]
        if actual != replacement or new.decrypt(actual.encode()) != plaintext:
            raise ValueError('recovery_rewrap_refused')
    return len(replacements)


def rewrap_candidate(active: Path, candidate: Path, source_secret: str, target_secret: str) -> dict:
    """Atomically replace only a stopped sibling candidate DB after full readback.

    A post-replace fsync failure is uncertain success, never automatic retry or
    authorization to activate. Source archive/active profile/key files untouched.
    """
    source, target = _secret(source_secret), _secret(target_secret)
    if (not all(p.is_absolute() and '..' not in p.parts for p in (active, candidate))
            or active == candidate or active.parent != candidate.parent):
        raise ValueError('recovery_rewrap_refused')
    original_id, candidate_id = _directory(active), _directory(candidate)
    database = candidate / 'arslan.db'
    staged = None
    try:
        with hold(active / 'arslan.db'), hold(database):
            if _directory(active) != original_id or _directory(candidate) != candidate_id:
                raise ValueError('recovery_rewrap_refused')
            for suffix in ('-wal', '-shm', '-journal'):
                sibling = database.with_name(database.name + suffix)
                if sibling.exists() or sibling.is_symlink():
                    raise ValueError('recovery_rewrap_refused')
            fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(fd, 'rb') as source_file:
                before = os.fstat(source_file.fileno())
                if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                        or before.st_nlink != 1 or before.st_size > 2 * 1024**3):
                    raise ValueError('recovery_rewrap_refused')
                fd, name = tempfile.mkstemp(prefix='.rewrap-', suffix='.db', dir=candidate)
                staged = Path(name)
                with os.fdopen(fd, 'wb') as output:
                    remaining = before.st_size
                    while remaining:
                        chunk = source_file.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError('recovery_rewrap_refused')
                        output.write(chunk)
                        remaining -= len(chunk)
                    if source_file.read(1):
                        raise ValueError('recovery_rewrap_refused')
                    output.flush()
                    os.fsync(output.fileno())
                with closing(sqlite3.connect(staged, timeout=0)) as db:
                    db.execute('PRAGMA trusted_schema=OFF')
                    db.execute('PRAGMA journal_mode=DELETE')
                    with db:
                        count = _rewrite(db, source, target)
                    if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                        raise ValueError('recovery_rewrap_refused')
                if (_stamp(os.fstat(source_file.fileno())) != _stamp(before)
                        or _stamp(database.lstat()) != _stamp(before)
                        or _directory(candidate) != candidate_id or _directory(active) != original_id):
                    raise ValueError('recovery_rewrap_refused')
                with staged.open('rb') as finished:
                    os.fsync(finished.fileno())
                os.replace(staged, database)
                staged = None
                parent_fd = os.open(candidate, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
        return {'rewrapped': True, 'credentials': count, 'secret_persisted': False}
    except Exception:
        raise ValueError('recovery_rewrap_refused') from None
    finally:
        if staged is not None:
            for path in (staged, *(Path(str(staged) + suffix) for suffix in ('-journal', '-wal', '-shm'))):
                path.unlink(missing_ok=True)
