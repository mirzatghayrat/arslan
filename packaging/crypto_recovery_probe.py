#!/usr/bin/env python3
"""Read-only: can any candidate salt open the secrets in a database? Answers, never writes.

    python3 packaging/crypto_recovery_probe.py --db <path> [--salt <file> ...]

WHY THIS EXISTS AND WHY IT ONLY READS. Spec ⓪ ruling: a write that follows a
successful decryption is a migration; a write that PRECEDES one is a gamble. Salts we
went looking for belong to the second kind, and the boundary the user set is "not one
byte before we nod". So this script opens the database READ-ONLY at the SQLite URI
level — not as a policy this code promises to follow, but as a mode the driver
enforces — and reports what it found.

It also prints no plaintext, ever. This output is meant to be pasted into a chat or a
ticket, and a recovery report that leaked the secrets it is reporting on would be a
worse fault than the one it describes. You get locations, states, and which candidate
opened what.

TWO HALVES OF A KEY. Every stored secret is encrypted under a key derived from
ARSLAN_SECRET_KEY (which lives OUTSIDE the data directory, by design) plus a per-install
salt. Losing either half is enough. This script needs the same ARSLAN_SECRET_KEY the
values were written under — set it in the environment before running — and lets you
hand it salts to try.

EXIT CODES: 0 = nothing needs recovering. 2 = something is recoverable. 3 = something
is unreadable and no candidate opened it. Never nonzero for "I changed something",
because it does not change anything.
"""
from __future__ import annotations

import argparse
import base64
import os
import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _load_salt(path: pathlib.Path) -> bytes:
    data = path.read_bytes()
    if len(data) < 16:
        raise SystemExit(f"{path}: {len(data)} bytes — a PBKDF2 salt is at least 16")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Read-only recovery probe for Arslan's encrypted settings.",
        epilog="Writes nothing. Prints no secret values.",
    )
    ap.add_argument("--db", required=True, type=pathlib.Path,
                    help="path to arslan.db (opened read-only)")
    ap.add_argument("--salt", action="append", default=[], type=pathlib.Path,
                    metavar="FILE", help="a candidate crypto_salt file to try; repeatable")
    args = ap.parse_args()

    if not args.db.is_file():
        raise SystemExit(f"no such database: {args.db}")
    if not os.environ.get("ARSLAN_SECRET_KEY", "").strip():
        print("⚠️  ARSLAN_SECRET_KEY is not set. Every value will look unreadable, because\n"
              "    the salt is only HALF the key. Set it to the value these secrets were\n"
              "    saved under and run again.\n", file=sys.stderr)

    # Point the app's config at this database WITHOUT letting it touch the real one.
    os.environ["ARSLAN_DB_PATH"] = str(args.db)
    os.environ.setdefault("ARSLAN_DATA_DIR", str(args.db.parent))
    os.environ["ARSLAN_SECRET_KEY_FILE"] = ""     # never read ~/.arslan/secret_key

    from server import crypto
    from server.services import crypto_boot

    extra = [(str(p), _load_salt(p)) for p in args.salt]

    # file:...?mode=ro — enforced by the driver, not merely intended by this script.
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    class _Ro:
        """The tiny slice of the SQLAlchemy connection API crypto_boot uses."""

        def exec_driver_sql(self, sql, params=()):
            return conn.execute(sql, params)

    ro = _Ro()
    row = conn.execute(
        "SELECT value FROM settings WHERE key='crypto_salt_b64'").fetchone()
    if row and row[0]:
        crypto.adopt_salt(base64.b64decode(row[0]), source="database")
        installed = "from the database"
    elif extra:
        crypto.adopt_salt(extra[0][1], source="probe-supplied")
        installed = f"none stored; using {extra[0][0]} as the current one"
    else:
        raise SystemExit(
            "this database has no salt row and you supplied no --salt, so there is\n"
            "nothing to derive a key from. Pass the install's crypto_salt file."
        )

    report = crypto_boot.probe_recovery_candidates(ro, extra_salts=extra)

    print(f"database      {args.db}")
    print(f"salt          {installed}")
    print(f"candidates    {', '.join(report['candidates_tried']) or '(none)'}")
    print(f"unreadable    {report['unreachable'] + report['recoverable']}")
    print(f"recoverable   {report['recoverable']}")
    print()
    if not report["findings"]:
        print("Everything stored here opens with the current key. Nothing to recover.")
        return 0
    for f in report["findings"]:
        where = f"{f['table']}.{f['ident']}"
        verdict = f"RECOVERABLE via {f['candidate']}" if f["candidate"] else "no candidate opened it"
        print(f"  {where:44} {verdict}")
    print()
    if report["recoverable"]:
        print("Nothing has been changed. Rewriting these under the current key is a\n"
              "separate, deliberate step — crypto_boot.recover_with_salt — and it is not\n"
              "wired into startup on purpose.")
        return 2
    print("No candidate salt opened these. The salt they were written under is not\n"
          "among the ones tried; another copy of the data directory may still have it.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
