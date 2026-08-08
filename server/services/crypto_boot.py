"""Resolve the PBKDF2 salt at boot and install it into :mod:`server.crypto`.

Runs inside the same transaction as the migration chain, on the sync connection, for
one reason: the salt has to be settled before anything decrypts, and ``crypto`` is
sync and reachable from every layer. Making derivation async to fetch it would push
that change across the whole codebase for a value that is read once.

WHY GENERATING A SALT HERE IS SAFE, AND WHERE IT IS NOT. On a fresh install there is
nothing to lose: no salt, no ciphertext, generate and persist. When ciphertext already
exists and the salt row does not, the salt has been LOST — and generating one is still
the right move, because the alternative is an install that cannot even accept a
re-entered key. What is NOT acceptable is doing it quietly. The old ciphertext stays
untouched (it may yet be recoverable from a candidate salt), and the fact is written
to a durable marker row.

🔴 THE MARKER EXISTS BECAUSE BOOTING DESTROYS THE EVIDENCE. "No salt row, but
ciphertext present" is the signature of a lost salt, and the moment this function
writes a salt row that signature is gone. Inferring it later from "the primary key
cannot open these rows" is weaker — a changed ARSLAN_SECRET_KEY produces the same
symptom, and telling those two apart is the whole point of the diagnosis. So the
distinguishing fact is recorded when it is still visible.
"""
from __future__ import annotations

import base64
import logging
import os

from server import crypto
from server.db.migrations.versions._0039_crypto_salt_into_db import SALT_SETTING_KEY

logger = logging.getLogger(__name__)

_SALT_LEN = 16

#: Durable record that a salt was generated while ciphertext already existed.
#: Value is the provenance string; the row's presence is the fact. Deliberately NOT in
#: any settings_service registry, so GET /settings cannot surface or round-trip it.
SALT_LOST_MARKER_KEY = "crypto_salt_lost_at_boot"

FROM_DATABASE = "database"
GENERATED_FRESH = "generated-fresh-install"
GENERATED_OVER_CIPHERTEXT = "generated-over-existing-ciphertext"

# Where encrypted values live. Each entry is (table, column, extra WHERE or None).
# Kept as data so "did this install have ciphertext?" has ONE answer, and so adding a
# fifth encrypted column is a one-line edit next to the others rather than a fourth
# place that quietly disagrees.
_CIPHERTEXT_SITES = (
    ("settings", "value",
     "key IN ('llm_api_key', 'search_api_key', 'github_token')"),
    ("provider_configs", "api_key", None),
    ("mcp_servers", "env", None),
)


def _tables(connection) -> set[str]:
    return {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _read_salt_row(connection) -> bytes | None:
    row = connection.exec_driver_sql(
        "SELECT value FROM settings WHERE key = ?", (SALT_SETTING_KEY,)).fetchone()
    if not row or not row[0]:
        return None
    # A corrupt row is NOT "absent". Both branches below fail LOUDLY rather than
    # falling through to generation, because generation would write a new salt over
    # ciphertext that the stored value might still have opened — turning a repairable
    # row into permanent loss. The same reasoning covers a too-short value: nothing in
    # this codebase ever writes fewer than _SALT_LEN bytes, so a short one means
    # something scribbled on it, not that there is no salt.
    try:
        data = base64.b64decode(row[0], validate=True)
    except (ValueError, TypeError):
        return _corrupt(f"settings.{SALT_SETTING_KEY} is not valid base64")
    if len(data) < _SALT_LEN:
        return _corrupt(
            f"settings.{SALT_SETTING_KEY} decodes to {len(data)} bytes, "
            f"fewer than the {_SALT_LEN} required"
        )
    return data


def _corrupt(detail: str) -> bytes:
    logger.error(
        "crypto: the stored PBKDF2 salt is unusable (%s); refusing to replace it. "
        "Stored secrets cannot be decrypted until it is repaired — a generated "
        "replacement would make them permanently unreadable.",
        detail,
    )
    raise crypto.CryptoNotInitializedError(f"stored PBKDF2 salt is corrupt: {detail}")


def _stored_ciphertext(connection):
    """Yield (table, pk_or_key, value) for every non-empty encrypted value present.

    Missing tables are skipped rather than raising: on a very first boot the schema
    may not be fully created yet, and a partially-built database must not be read as
    a data-loss event.
    """
    present = _tables(connection)
    for table, column, where in _CIPHERTEXT_SITES:
        if table not in present:
            continue
        ident = "key" if table == "settings" else "id"
        sql = (f"SELECT {ident}, {column} FROM {table} "
               f"WHERE {column} IS NOT NULL AND {column} != ''")
        if where:
            sql += f" AND {where}"
        for row in connection.exec_driver_sql(sql).fetchall():
            yield table, row[0], row[1]


def _has_unreachable_ciphertext(connection) -> bool:
    """True when a stored value exists that the CURRENT inputs cannot open.

    🔴 Not "does ciphertext exist?" — that question gives a FALSE data-loss alarm on
    the most ordinary upgrade there is. An install predating d6d8afa8 stores unsalted,
    bare-SHA256 ciphertext and has no salt file at all, so it arrives here with rows
    present and no salt row, which "does ciphertext exist?" reads as loss. Nothing was
    lost: the legacy key opens every one of those, and the sweep below re-encrypts
    them minutes later.

    A false alarm is not the safe direction. It teaches its reader to skip the
    message, which costs exactly the one time it is real.

    Only the LEGACY key is consulted, because at this point no salt is installed and
    the primary key cannot be derived. That is the correct test anyway: if a value
    needs the primary key, it was written under some salt, and the salt is missing.
    """
    legacy = crypto.legacy_fernet()
    for _table, _ident, value in _stored_ciphertext(connection):
        try:
            legacy.decrypt(value.encode("utf-8"))
        except Exception:  # noqa: BLE001 — any failure to open means "not reachable"
            return True
    return False


def _write_setting(connection, key: str, value: str) -> None:
    connection.exec_driver_sql(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def resolve_and_adopt_salt(connection) -> str:
    """Install the process-wide PBKDF2 salt; return where it came from.

    Order matters: read before write, and check for ciphertext BEFORE persisting a
    generated salt, because the write is what erases the evidence.
    """
    if "settings" not in _tables(connection):
        # Nothing to read or write yet. Deliberately does NOT install a salt — a
        # caller that proceeds to decrypt will get CryptoNotInitializedError, which
        # is the honest outcome, rather than a guess that looks like success.
        logger.warning("crypto: no settings table at boot; PBKDF2 salt not installed")
        return "unavailable"

    stored = _read_salt_row(connection)
    if stored is not None:
        crypto.adopt_salt(stored, source=FROM_DATABASE)
        return FROM_DATABASE

    lost = _has_unreachable_ciphertext(connection)
    salt = os.urandom(_SALT_LEN)
    _write_setting(connection, SALT_SETTING_KEY, base64.b64encode(salt).decode("ascii"))
    source = GENERATED_OVER_CIPHERTEXT if lost else GENERATED_FRESH

    if lost:
        _write_setting(connection, SALT_LOST_MARKER_KEY, source)
        logger.error(
            "crypto: this database holds encrypted values but its PBKDF2 salt was "
            "missing, so a NEW salt was generated. The existing secrets were encrypted "
            "under the old salt and cannot be decrypted with this one — your "
            "ARSLAN_SECRET_KEY is not the missing half. The old ciphertext has been "
            "left untouched. This has been recorded in settings.%s.",
            SALT_LOST_MARKER_KEY,
        )
    else:
        logger.info("crypto: generated this install's PBKDF2 salt (first boot).")

    crypto.adopt_salt(salt, source=source)
    return source


class MigrationVerificationError(RuntimeError):
    """A re-encrypted value did not read back. The transaction must not commit.

    Distinct from a decryption failure on purpose: this one means WE produced
    something unreadable, which is the only outcome of this sweep that could destroy
    data rather than merely fail to recover it.
    """


def migrate_legacy_ciphertext(connection) -> int:
    """Re-encrypt group-A ciphertext under the primary key. Returns how many moved.

    GROUP A ONLY — values the current inputs can already open (here: the legacy
    unsalted key; the primary needs no migration by definition). Anything neither key
    opens is group B: left exactly as found, because rewriting what we cannot read is
    the gamble the split exists to forbid, and an untouched row is still a candidate
    for recovery.

    NOT GATED, deliberately. d6d8afa8 added read-time fallback to the legacy key and
    treated that as the migration. It was not: the ciphertext was never rewritten, so
    the legacy key could never be retired and the next keyring change lost it. A human
    gate in front of this half would reproduce that — the legacy format kept alive by
    caution. The gate belongs on group B, where the decryption has not succeeded yet.

    Each rewrite is verified by reading it back with the PRIMARY key alone before the
    count moves. A failure raises, which rolls the whole sweep back rather than
    leaving a row we made unreadable.
    """
    if "settings" not in _tables(connection):
        return 0
    legacy = crypto.legacy_fernet()
    primary = crypto.primary_fernet()
    migrated = 0

    for table, ident, value in list(_stored_ciphertext(connection)):
        raw = value.encode("utf-8")
        try:
            primary.decrypt(raw)
            continue                      # already current
        except Exception:                 # noqa: BLE001
            pass
        try:
            plaintext = legacy.decrypt(raw).decode("utf-8")
        except Exception:                 # noqa: BLE001
            continue                      # group B — not ours to touch
        replacement = crypto.encrypt(plaintext)
        try:
            if primary.decrypt(replacement.encode("utf-8")).decode("utf-8") != plaintext:
                raise MigrationVerificationError(f"{table} row {ident!r} read back wrong")
        except MigrationVerificationError:
            raise
        except Exception as exc:          # noqa: BLE001
            raise MigrationVerificationError(
                f"{table} row {ident!r} did not read back after re-encryption"
            ) from exc
        column = next(c for t, c, _ in _CIPHERTEXT_SITES if t == table)
        id_col = "key" if table == "settings" else "id"
        connection.exec_driver_sql(
            f"UPDATE {table} SET {column} = ? WHERE {id_col} = ?", (replacement, ident))
        migrated += 1

    if migrated:
        logger.info(
            "crypto: re-encrypted %d legacy (unsalted) value(s) under the current key; "
            "the legacy key is no longer required to read them.", migrated)
    return migrated


# --------------------------------------------------------------------------- #
# Group B — candidate salts. TRIED and REPORTED here; rewriting needs a person.
# --------------------------------------------------------------------------- #

FALLBACK_CANDIDATE = "fallback-salt-constant"
DATA_DIR_FILE_CANDIDATE = "data-dir-salt-file"


def _data_dir_salt_file() -> bytes | None:
    """The legacy ``<data_dir>/crypto_salt``, if it is still there and usable.

    Inert for derivation since step 2, but a salt sitting next to a database whose
    row says something different is exactly the thing worth trying.
    """
    try:
        from server import config

        path = config.data_dir() / "crypto_salt"
        data = path.read_bytes() if path.exists() else None
    except (OSError, ImportError):
        return None
    return data if data and len(data) >= _SALT_LEN else None


def _candidates(connection, extra_salts) -> list[tuple[str, bytes]]:
    """Candidate (label, salt) pairs, most deliberate first.

    Operator-supplied salts lead because someone went and found them on purpose. The
    fallback constant is last: it is the least likely and the least specific.
    """
    out: list[tuple[str, bytes]] = [(str(label), bytes(salt)) for label, salt in extra_salts]
    installed = _read_salt_row(connection)
    from_file = _data_dir_salt_file()
    if from_file and from_file != installed:
        out.append((DATA_DIR_FILE_CANDIDATE, from_file))
    out.append((FALLBACK_CANDIDATE, crypto._FALLBACK_SALT))

    seen: set[bytes] = set()
    unique = []
    for label, salt in out:
        if salt in seen or salt == installed:
            continue          # already covered by the primary key
        seen.add(salt)
        unique.append((label, salt))
    return unique


def _fernet_for_salt(salt: bytes):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=crypto._PBKDF2_ITERATIONS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(crypto._active_secret().encode("utf-8"))))


def _opens(fernet, value: str) -> str | None:
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None


def _group_a_can_open(value: str) -> bool:
    return (_opens(crypto.primary_fernet(), value) is not None
            or _opens(crypto.legacy_fernet(), value) is not None)


def probe_recovery_candidates(connection, *, extra_salts=()) -> dict:
    """Which stored values could be recovered, and by which candidate salt.

    🔴 STRICTLY READ-ONLY. This is the "gamble" half of the split: the salts tried
    here were found rather than derived from the configured inputs, so even a
    successful decryption does not authorise a rewrite. The user's boundary: not one
    byte before we nod. :func:`recover_with_salt` is the gated counterpart.

    🔴 NO PLAINTEXT IN THE RETURN VALUE. This report is logged and shown on screen. A
    recovery report that carried the secrets it is reporting about would be a worse
    leak than the fault it describes, so findings name a location and a candidate
    label and nothing else.

    Values group A can already open are omitted entirely — they need no recovery, and
    listing them would bury the one line that matters under a healthy install's rows.
    """
    if "settings" not in _tables(connection):
        return {"recoverable": 0, "unreachable": 0, "findings": [], "candidates_tried": []}

    candidates = _candidates(connection, extra_salts)
    findings, recoverable, unreachable = [], 0, 0

    for table, ident, value in _stored_ciphertext(connection):
        if ident == SALT_SETTING_KEY or _group_a_can_open(value):
            continue
        hit = next((label for label, salt in candidates
                    if _opens(_fernet_for_salt(salt), value) is not None), None)
        findings.append({"table": table, "ident": ident, "candidate": hit})
        if hit:
            recoverable += 1
        else:
            unreachable += 1

    logger.info(
        "crypto: recovery probe — %d recoverable, %d unreachable, candidates tried: %s",
        recoverable, unreachable, ", ".join(label for label, _ in candidates) or "none")
    return {"recoverable": recoverable, "unreachable": unreachable,
            "findings": findings, "candidates_tried": [label for label, _ in candidates]}


def recover_with_salt(connection, salt: bytes) -> int:
    """Re-encrypt, under the current key, every value the GIVEN salt opens.

    The gated counterpart to :func:`probe_recovery_candidates`. Deliberately not
    called from boot — a caller has to name a salt, which is the human decision. Each
    rewrite is verified by reading it back with the primary key alone, exactly as the
    group-A sweep does; a failure raises and takes the transaction with it.
    """
    if "settings" not in _tables(connection):
        return 0
    fernet = _fernet_for_salt(bytes(salt))
    primary = crypto.primary_fernet()
    moved = 0

    for table, ident, value in list(_stored_ciphertext(connection)):
        if ident == SALT_SETTING_KEY or _opens(primary, value) is not None:
            continue
        plaintext = _opens(fernet, value)
        if plaintext is None:
            continue
        replacement = crypto.encrypt(plaintext)
        if _opens(primary, replacement) != plaintext:
            raise MigrationVerificationError(
                f"{table} row {ident!r} did not read back after recovery")
        column = next(c for t, c, _ in _CIPHERTEXT_SITES if t == table)
        id_col = "key" if table == "settings" else "id"
        connection.exec_driver_sql(
            f"UPDATE {table} SET {column} = ? WHERE {id_col} = ?", (replacement, ident))
        moved += 1

    if moved:
        logger.warning(
            "crypto: recovered %d value(s) using an operator-supplied salt and "
            "re-encrypted them under the current key.", moved)
    return moved
