"""First-boot ARSLAN_SECRET_KEY bootstrap (dev-only, lock-and-box).

A stranger's first ``uvicorn server.main:app`` used to require one manual
``python3 -c 'import secrets; ...'`` step — the only mandatory command in the
whole first-run flow, and the one that broke on stock macOS (no ``python``).
This module removes it n8n-style: a keyless DEV boot generates a secret once,
persists it OUTSIDE the data dir, and reuses it on every later boot.

Boundaries (approved spec):
  * dev-only: ``ARSLAN_ENV=prod`` never reads or writes the file — prod keeps
    the explicit-env-or-refuse-boot contract (``server.main._validate_settings``).
  * lock-and-box: the file lives OUTSIDE ``ARSLAN_DATA_DIR`` (default
    ``~/.arslan/secret_key``, override ``ARSLAN_SECRET_KEY_FILE``) so copying
    the data dir alone never ships the key next to the ciphertext. If the
    resolved path lands INSIDE the data dir we still work but disclose that the
    separation is void instead of claiming a two-piece backup.
  * precedence: explicit ``ARSLAN_SECRET_KEY`` > persisted file > fresh
    generation. An existing non-blank file is never overwritten; env != file
    logs ONE warning naming the path (never any value). A BLANK file is not a
    secret (a poisoned/failed earlier write) and is regenerated over.
  * disclosure: generation logs one line naming the file and the backup rule.
    Failure to persist falls back to the pre-existing insecure-dev-fallback
    behaviour (``server.crypto``) with a warning — returning an UNPERSISTED
    fresh secret would rotate the key every boot and brick stored BYOK keys,
    which is strictly worse.
  * a read error on an EXISTING file is NOT "absent": regenerating over a file
    we merely failed to read would rotate the secret and permanently brick
    every stored provider key (crypto derives both MultiFernet keys from the
    CURRENT secret). Fail back to the dev fallback instead and say why.

Ordering discipline (plan adversarial review): the prod and disabled gates run
BEFORE any filesystem access, so prod boots and disabled runs (the test suites
pin ``ARSLAN_SECRET_KEY_FILE=""`` at conftest module top) can never stat, read,
or warn about the real ``~/.arslan``.

Import discipline: ``server.config`` imports this module at module-import time,
so it must stay stdlib-only — importing anything under ``server.*`` here would
cycle through ``server.config``.
"""
from __future__ import annotations

import logging
import os
import secrets
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

SECRET_FILE_ENV = "ARSLAN_SECRET_KEY_FILE"
_SECRET_DIRNAME = ".arslan"
_SECRET_FILENAME = "secret_key"


def _resolve_secret_path(raw: str | None) -> Path:
    """Resolve the persisted-secret path (override or default), normalized.

    Mirrors ``server.config._resolve_data_dir``: env values arrive unexpanded
    from systemd/docker env files, so ``~``/``$VAR`` must be expanded here or a
    literal ``./~`` directory gets created under CWD.
    """
    p = Path(raw) if raw else Path.home() / _SECRET_DIRNAME / _SECRET_FILENAME
    return Path(os.path.expandvars(os.path.expanduser(str(p)))).resolve()


def _persist_secret(path: Path, secret: str, *, overwrite_blank: bool) -> None:
    """Write owner-only; chmod 0o700 ONLY a parent dir we created ourselves.

    Same fd pattern as ``server.token_bootstrap._write_token`` (duplicated —
    importing it here would cycle via ``server.auth``), hardened two ways:
    fchmod(0o600) runs BEFORE the secret bytes land (O_CREAT's mode applies
    only to NEW files, so on the blank-file self-heal path the bytes would
    otherwise sit in a still-lax file until the trailing chmod), and creation
    is O_EXCL unless we are deliberately healing a KNOWN-blank file — two
    concurrent keyless first boots must not each persist a different secret
    (the loser would serve an unpersisted one; the caller converts the
    FileExistsError loss into loading the winner's value). The O_TRUNC
    self-heal path keeps a tiny same-shape race, confined to already-blank
    (poisoned) files. A PRE-existing parent is never chmod'ed — it could be
    ``$HOME`` when ``ARSLAN_SECRET_KEY_FILE`` points directly under it.
    """
    parent = path.parent
    created_parent = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    if created_parent:
        os.chmod(parent, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite_blank else os.O_EXCL)
    fd = os.open(path, flags, 0o600)
    try:
        # fchmod BEFORE the bytes land: O_CREAT's mode applies only to NEW files, so
        # on the blank-file self-heal path the secret would otherwise sit in a
        # possibly-lax file until a trailing chmod. This single call is the whole
        # permission guarantee — no trailing chmod is needed.
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        os.write(fd, secret.encode("utf-8"))
    finally:
        os.close(fd)


def _tighten_permissions(path: Path, *, log: logging.Logger) -> None:
    """A loaded key file readable by group/other is quietly fixed to 0o600."""
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            log.info("Tightened permissions on %s to owner-only (was %03o).", path, mode)
    except OSError as exc:
        log.warning(
            "Could not verify/tighten permissions on %s (%s).", path, exc.__class__.__name__
        )


def _warn_on_mismatch(path: Path, explicit: str, *, log: logging.Logger) -> None:
    """Explicit env differs from the persisted file -> one warning, no values.

    Compared STRIPPED on both sides: crypto strips before deriving
    (``server.crypto._active_secret``), so values that differ only in
    surrounding whitespace derive the identical key and must not warn.
    """
    try:
        persisted = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Absent, unreadable, or non-UTF-8 (e.g. a raw `openssl rand 32` file):
        # nothing to compare, explicit wins anyway — never let the mismatch
        # check crash an explicit-key boot.
        return
    if persisted.strip() and persisted.strip() != explicit.strip():
        log.warning(
            "ARSLAN_SECRET_KEY is set explicitly and differs from the persisted secret at "
            "%s; the explicit value wins. If stored provider keys fail to decrypt, check "
            "which secret they were written under.",
            path,
        )


def _log_disclosure(path: Path, data_dir, *, log: logging.Logger) -> None:
    inside = False
    if data_dir is not None:
        try:
            inside = path.is_relative_to(Path(data_dir).resolve())
        except (OSError, ValueError):
            inside = False
    if inside:
        log.warning(
            "Generated ARSLAN_SECRET_KEY (first run) and stored it at %s — NOTE this is "
            "INSIDE your data dir, so a data-dir backup ships the encryption key next to "
            "the encrypted secrets (lock-and-box separation is void). Move it with "
            "ARSLAN_SECRET_KEY_FILE or set ARSLAN_SECRET_KEY explicitly.",
            path,
        )
    else:
        log.warning(
            "Generated ARSLAN_SECRET_KEY (first run) and stored it at %s. A full backup is "
            "TWO pieces: your data dir AND this file. Set ARSLAN_SECRET_KEY explicitly to "
            "manage the secret yourself.",
            path,
        )


def bootstrap_secret_key(
    *, env: str, explicit: str, data_dir=None, log: logging.Logger = logger
) -> str:
    """Resolve the effective ARSLAN_SECRET_KEY for this boot (see module docstring).

    Called from ``server.config.load_settings`` — i.e. at first ``server.*``
    import and on every ``importlib.reload(server.config)``. Idempotent: a
    persisted secret is loaded, never regenerated. Returns the explicit value
    VERBATIM when one is set (crypto owns the strip semantics); returns ``""``
    when the feature is off/unavailable, preserving the pre-existing
    insecure-dev-fallback behaviour.
    """
    raw_override = os.environ.get(SECRET_FILE_ENV)

    # Gate 1 — prod: never any filesystem access (explicit-or-refuse contract).
    if env == "prod":
        if raw_override and raw_override.strip():
            log.info(
                "ARSLAN_SECRET_KEY_FILE is dev-only and ignored in prod; "
                "set ARSLAN_SECRET_KEY explicitly."
            )
        return explicit

    # Gate 2 — set-but-empty override disables the feature (test suites / opt-out).
    if raw_override is not None and not raw_override.strip():
        return explicit

    path = _resolve_secret_path(raw_override)

    # Precedence 1 — explicit env wins; only a path-naming mismatch warning.
    if explicit.strip():
        _warn_on_mismatch(path, explicit, log=log)
        return explicit

    # Precedence 2 — persisted file.
    try:
        persisted = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        persisted = None
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError included: a non-UTF-8 file (raw random bytes) is a
        # read failure on an EXISTING file, not "absent" — never regenerate over it.
        log.warning(
            "Could not read the persisted ARSLAN_SECRET_KEY at %s (%s); refusing to "
            "regenerate over it — falling back to the insecure dev key for this boot.",
            path,
            exc.__class__.__name__,
        )
        return ""
    if persisted is not None and persisted.strip():
        _tighten_permissions(path, log=log)
        log.info("Loaded ARSLAN_SECRET_KEY from %s.", path)
        return persisted.strip()

    # Precedence 3 — first run (absent or blank file): generate + persist + disclose.
    secret = secrets.token_urlsafe(32)
    try:
        _persist_secret(path, secret, overwrite_blank=persisted is not None)
    except FileExistsError:
        # Lost a concurrent first-boot race (another process created the file
        # between our read and our O_EXCL create). Serve the WINNER's persisted
        # value so every process runs on the same secret — returning our own
        # unpersisted candidate would brick any BYOK key saved through it.
        try:
            won = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            won = ""
        if won.strip():
            log.info("Loaded ARSLAN_SECRET_KEY from %s (concurrent first boot).", path)
            return won.strip()
        log.warning(
            "Concurrent first boot left %s unreadable/blank; falling back to the "
            "insecure dev key for this boot.",
            path,
        )
        return ""
    except OSError as exc:
        log.warning(
            "Could not persist an auto-generated ARSLAN_SECRET_KEY to %s (%s); falling "
            "back to the insecure dev key for this boot. Set ARSLAN_SECRET_KEY explicitly "
            "or make the location writable.",
            path,
            exc.__class__.__name__,
        )
        return ""
    _log_disclosure(path, data_dir, log=log)
    return secret
