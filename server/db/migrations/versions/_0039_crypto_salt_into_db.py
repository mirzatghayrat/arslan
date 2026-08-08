"""0039: move the PBKDF2 salt into the database, next to the ciphertext it protects.

WHY. The Fernet key is derived from two halves: ``ARSLAN_SECRET_KEY`` and a
per-install salt. The secret lives OUTSIDE the data dir on purpose
(``server/secret_bootstrap.py`` — a stolen data-dir backup must not carry the key).
The salt lived at ``<data_dir>/crypto_salt``, a plain file, and
``crypto._load_or_create_salt`` generated a fresh random one whenever that path was
missing. Three routes therefore separated the salt from the ciphertext it was the
only key to: a data-dir change, an ``OSError`` falling back to a fixed constant, and
a backup that carried one half. Once separated there was no way back — the keyring
held exactly two keys, the current salt's and a legacy unsalted one, so ciphertext
written under any OTHER salt was unreadable by design.

A PBKDF2 salt is not a secret; it only has to be unique and stable. So it can live
with the ciphertext, and that is the one arrangement where both properties hold at
once: the two halves of a backup stay self-consistent (database = ciphertext + salt,
worthless alone), and the secret still stands apart.

WHAT THIS MIGRATION DOES, AND DELIBERATELY DOES NOT DO.

It ADOPTS an existing ``<data_dir>/crypto_salt`` verbatim. Adoption, not generation:
copying the bytes keeps the derived key bit-for-bit identical, so an install that
works today notices nothing. Generating a new salt here would brick every stored
secret on the spot — the failure this whole change exists to prevent, caused by the
migration meant to prevent it.

It does NOT invent a salt when the file is absent. That state — no salt row, no salt
file, yet ciphertext in the tables — is precisely the "the salt was lost" case, and
it has to stay observable so the diagnosis can name which half went missing instead
of guessing. A fresh install has no ciphertext either, and gets its salt on first
encrypt.

It does NOT verify the adopted salt against real ciphertext. That check needs the
secret, and pulling ``server.crypto`` in here would give a schema migration an
opinion about key derivation. Verification belongs to the boot-time crypto init that
runs after this, where both halves are already in hand.

The old file is left in place, unread by the new derivation path. It stays as a
recovery candidate: deleting it would destroy the only way back for an install whose
salt row and file have already diverged.
"""
from __future__ import annotations

import base64

# The settings row that carries the salt. Deliberately NOT registered in
# settings_service._PLAIN_KEYS / _SECRET_KEYS / _INT_KEYS / _BOOL_KEYS: get_settings()
# builds its response by walking those registries, so an unregistered row is not
# reachable through GET /settings. It is not a secret, but it is not a user setting
# either, and it must never appear in a form the settings screen can round-trip.
SALT_SETTING_KEY = "crypto_salt_b64"

_SALT_FILENAME = "crypto_salt"
_MIN_SALT_LEN = 16


def _tables(connection) -> set[str]:
    return {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _existing_salt_row(connection) -> str | None:
    row = connection.exec_driver_sql(
        "SELECT value FROM settings WHERE key = ?", (SALT_SETTING_KEY,),
    ).fetchone()
    return row[0] if row else None


def _salt_file_bytes() -> bytes | None:
    """The bytes of ``<data_dir>/crypto_salt``, or None if unusable.

    Uses ``server.config``'s single data-dir resolver rather than re-reading the
    environment: a second reading of ARSLAN_DATA_DIR is how the salt and the
    subsystems' files came apart in the first place.
    """
    try:
        from server import config

        path = config.data_dir() / _SALT_FILENAME
        if not path.exists():
            return None
        data = path.read_bytes()
    except (OSError, ImportError):
        return None
    return data if len(data) >= _MIN_SALT_LEN else None


def _upgrade(connection) -> None:
    if "settings" not in _tables(connection):
        return
    if _existing_salt_row(connection) is not None:
        return                                  # idempotent: already adopted
    data = _salt_file_bytes()
    if data is None:
        return                                  # nothing to adopt; see docstring
    connection.exec_driver_sql(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        (SALT_SETTING_KEY, base64.b64encode(data).decode("ascii")),
    )


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    """Deliberately a no-op.

    Dropping the row would put the install back into the state this migration
    exists to make impossible — and, unlike a dropped column, it would take the
    only copy of a live decryption key half with it whenever the old file has
    since been removed.
    """
    return
