"""The operator-facing recovery probe: it answers, and it does not write.

This script is the thing a person runs against a REAL database when their keys have
stopped opening — including the author's own, which is why every assertion here is
about restraint rather than capability. It runs as a subprocess, the way it is
actually used, because the read-only guarantee is a property of the process (a SQLite
`mode=ro` URI) and not of a function this test could call politely.

Three properties, and the byte-identity one is the reason the file exists:

  1. it finds what a supplied candidate salt can open, and names the candidate
  2. the database is byte-identical afterwards
  3. nothing it prints contains a secret value

Property 2 is asserted by hashing the file before and after. "I read the code and saw
no INSERT" is the kind of source-level reasoning this project has been caught by
repeatedly; a hash is an observation.
"""
from __future__ import annotations

import base64
import hashlib
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from server import crypto

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "packaging" / "crypto_recovery_probe.py"
SECRET = "the-secret-these-values-were-written-under"
PLAINTEXT = "tvly-the-value-that-must-never-be-printed"
LOST_SALT = bytes(range(200, 216))
CURRENT_SALT = bytes(range(10, 26))


def _fernet(salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=crypto._PBKDF2_ITERATIONS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(SECRET.encode())))


@pytest.fixture
def install(tmp_path):
    """A database whose search key was written under a salt the row no longer holds."""
    db = tmp_path / "arslan.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO settings VALUES (?, ?)",
                 ("crypto_salt_b64", base64.b64encode(CURRENT_SALT).decode()))
    conn.execute("INSERT INTO settings VALUES (?, ?)",
                 ("search_api_key", _fernet(LOST_SALT).encrypt(PLAINTEXT.encode()).decode()))
    conn.execute("INSERT INTO settings VALUES (?, ?)",
                 ("github_token", _fernet(CURRENT_SALT).encrypt(b"ghp-fine").decode()))
    conn.commit()
    conn.close()
    (tmp_path / "lost_salt").write_bytes(LOST_SALT)
    return tmp_path


def _run(install, *extra):
    env = {**os.environ, "ARSLAN_SECRET_KEY": SECRET, "ARSLAN_SECRET_KEY_FILE": "",
           "ARSLAN_DATA_DIR": str(install)}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(install / "arslan.db"), *extra],
        capture_output=True, text=True, env=env, cwd=str(REPO), timeout=180,
    )


def _digest(install) -> str:
    return hashlib.sha256((install / "arslan.db").read_bytes()).hexdigest()


def test_it_finds_the_recoverable_value_and_names_the_candidate(install):
    r = _run(install, "--salt", str(install / "lost_salt"))

    assert r.returncode == 2, r.stderr        # 2 = something is recoverable
    assert "search_api_key" in r.stdout
    assert "RECOVERABLE" in r.stdout
    assert "lost_salt" in r.stdout
    # The healthy one must not be listed — a report that lists everything buries the
    # one line that matters.
    assert "github_token" not in r.stdout


def test_the_database_is_byte_identical_afterwards(install):
    before = _digest(install)

    _run(install, "--salt", str(install / "lost_salt"))

    assert _digest(install) == before, "the probe modified the database it was reading"


def test_it_prints_no_secret_value(install):
    r = _run(install, "--salt", str(install / "lost_salt"))

    assert PLAINTEXT not in r.stdout
    assert PLAINTEXT not in r.stderr


def test_without_a_candidate_it_says_so_rather_than_claiming_success(install):
    # Exit 3, not 0: "unreadable and I could not help" is a different answer from
    # "nothing needs recovering", and conflating them is the whole family of defect
    # this spec is about.
    r = _run(install)

    assert r.returncode == 3, r.stdout
    assert "no candidate opened it" in r.stdout


def test_a_healthy_database_reports_nothing_to_do(install):
    # The other side, so "it always finds something" cannot pass.
    conn = sqlite3.connect(install / "arslan.db")
    conn.execute("DELETE FROM settings WHERE key='search_api_key'")
    conn.commit()
    conn.close()

    r = _run(install, "--salt", str(install / "lost_salt"))

    assert r.returncode == 0, r.stdout
    assert "Nothing to recover" in r.stdout


def test_a_short_salt_file_is_refused(install):
    (install / "junk").write_bytes(b"tooshort")

    r = _run(install, "--salt", str(install / "junk"))

    assert r.returncode not in (0, 2, 3)
    assert "at least 16" in (r.stderr + r.stdout)
