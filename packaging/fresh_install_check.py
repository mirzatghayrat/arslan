#!/usr/bin/env python3
"""Assert that a built .app behaves like a FIRST install (S4.3-a §6).

    packaging/fresh_install_check.py path/to/Arslan.app

WHY THIS EXISTS: a developer never sees a first install. Their database is
always full, their ~/.arslan always has a key, their shell always exports
ARSLAN_DATA_DIR. Every "it works on my machine" bug in a desktop app lives in
that gap. So this runs the real bundle against a HOME that has never seen
Arslan, and asserts on what a stranger would actually get.

The assertions are deliberately two-sided. "Zero chats" alone is satisfied by
an app that created no database at all, so each emptiness check is paired with
an existence check: the table must BE there and be empty. Same for the data
directory — it must exist in the right place AND not exist inside the bundle.

Exits non-zero with a named reason. Prints every failure, not just the first:
one broken assumption usually breaks several, and finding them one build at a
time is the expensive way.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import base64
import http.client
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
PORT_RE = re.compile(r"http://127\.0\.0\.1:(\d+)")
BOOT_TIMEOUT = 120


def _latest_schema_version() -> str:
    """Read the head migration from the source of truth, not a literal.

    Hardcoding "0036" here would make this check pass forever after the next
    migration is added — the exact failure the assertion is meant to catch.
    """
    sys.path.insert(0, str(REPO))
    from server.db.migrations.runner import head

    return head()


def _factory_spawn_names() -> set[str]:
    """Likewise: the expected spawns come from DEFAULT_SPAWNS, not a count.

    A literal 6 would go stale the moment a seventh ships, and would then be
    wrong in the direction that reads as "the seeder is broken".
    """
    sys.path.insert(0, str(REPO))
    from server.services.default_spawns import DEFAULT_SPAWNS

    return {s["name"] for s in DEFAULT_SPAWNS}


class Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes: list[str] = []

    def ok(self, cond: bool, label: str, detail: str = "") -> bool:
        if cond:
            self.passes.append(label)
        else:
            self.failures.append(f"{label}{': ' + detail if detail else ''}")
        return cond

    def report(self) -> int:
        for p in self.passes:
            print(f"  PASS  {p}")
        for f in self.failures:
            print(f"  FAIL  {f}", file=sys.stderr)
        print(f"\n{len(self.passes)} passed, {len(self.failures)} failed")
        return 1 if self.failures else 0


def check_bundle_contents(app: pathlib.Path, c: Checks) -> None:
    """What ships inside the .app. Cheap, and independent of running it."""
    dbs = [p for p in app.rglob("*") if p.suffix in (".db", ".sqlite", ".sqlite3")]
    c.ok(
        not dbs,
        "the bundle carries no database",
        f"found {[str(p.relative_to(app)) for p in dbs]} — that would be somebody "
        "else's data, and would shadow the user's own",
    )

    secretish = [
        p
        for p in app.rglob("*")
        if p.name in (".env", "api_token", "secret_key", "crypto_salt")
        or p.suffix in (".p12", ".p8")
    ]
    c.ok(not secretish, "the bundle carries no secrets",
         f"found {[str(p.relative_to(app)) for p in secretish]}")

    sidecar = app / "Contents/Resources/sidecar/arslan-server"
    c.ok(sidecar.is_file() and os.access(sidecar, os.X_OK),
         "the sidecar is present and executable", str(sidecar))


def boot(app: pathlib.Path, home: pathlib.Path) -> tuple[subprocess.Popen, int, pathlib.Path]:
    """Launch the app against a clean HOME and wait for it to serve."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    # Deliberately POISONED: a real developer's shell exports this, and the
    # packaged app must ignore it. Leaving it out would make the check weaker
    # than reality.
    env["ARSLAN_DATA_DIR"] = "data"
    for var in ("ARSLAN_SECRET_KEY", "ARSLAN_API_TOKEN", "ARSLAN_STATIC_DIR"):
        env.pop(var, None)

    cwd = home / "launched-from"
    cwd.mkdir(parents=True, exist_ok=True)
    log = home / "app.log"
    proc = subprocess.Popen(
        [str(app / "Contents/MacOS/arslan-desktop")],
        stdout=log.open("wb"), stderr=subprocess.STDOUT, env=env, cwd=str(cwd),
    )

    deadline = time.time() + BOOT_TIMEOUT
    port = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(
                f"the app exited during boot (code {proc.returncode}):\n"
                + log.read_text(errors="replace")[-2000:]
            )
        m = PORT_RE.search(log.read_text(errors="replace"))
        if m:
            port = int(m.group(1))
            break
        time.sleep(1)
    if port is None:
        proc.kill()
        raise SystemExit(f"no port announced within {BOOT_TIMEOUT}s:\n"
                         + log.read_text(errors="replace")[-2000:])

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=2) as r:
                if r.status == 200:
                    return proc, port, log
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    proc.kill()
    raise SystemExit(f"port {port} never served /api/v1/health")


def check_runtime(port: int, home: pathlib.Path, log: pathlib.Path, c: Checks) -> None:
    # ---- the UI is actually served ------------------------------------
    for path, label in (("/", "the UI is served at /"),
                        ("/api/v1/health", "the API answers")):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
                body = r.read(400)
                c.ok(r.status == 200, label, f"HTTP {r.status}")
                if path == "/":
                    # 200 is not enough: the SPA fallback returns index.html,
                    # and an empty or wrong document would still be a 200.
                    c.ok(b"<html" in body.lower(), "/ returns an HTML document",
                         repr(body[:80]))
        except Exception as e:  # noqa: BLE001
            c.ok(False, label, str(e))

    # ---- data landed in the right place, and only there ----------------
    appsup = home / "Library/Application Support/Arslan"
    c.ok(appsup.is_dir(), "data dir is the per-platform app-data path", str(appsup))
    c.ok(not (home / "launched-from/data").exists(),
         "an inherited ARSLAN_DATA_DIR was ignored",
         "a data/ directory appeared next to the launch CWD")
    c.ok((home / ".arslan/secret_key").is_file(),
         "a secret key was generated on first run")

    db = appsup / "arslan.db"
    if not c.ok(db.is_file(), "the database was created", str(db)):
        return

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        # ---- migrations ran to head -----------------------------------
        want = _latest_schema_version()
        if c.ok("schema_version" in tables, "schema_version table exists"):
            applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
            c.ok(want in applied, f"migrations ran to head ({want})",
                 f"applied={sorted(applied)[-3:]}")

        # ---- everything a new user should NOT have --------------------
        # Paired: the table must EXIST and be EMPTY. Counting rows in a table
        # that was never created would raise, not report zero — but an app
        # that created no tables at all would then fail here loudly rather
        # than looking like a clean install.
        for table, label in (
            ("arslan_messages", "no conversations with the host"),
            ("arslan_summaries", "no conversation summaries"),
            ("conversation_events", "no conversation history"),
            ("runs", "no dispatch history"),
            ("user_facts", "no brain facts"),
            ("learnings", "no brain insights"),
            ("notes", "no brain notes"),
            ("knowledge_chunks", "no brain material"),
        ):
            if not c.ok(table in tables, f"{table} table exists"):
                continue
            n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
            c.ok(n == 0, label, f"{table} has {n} rows on a fresh install")

        # ---- chat_messages is NOT expected to be empty ----------------
        # Each spawn's private chat opens with one greeting from that spawn,
        # written when the spawn is created. This check originally asserted
        # zero rows here and failed on a correct build — the spec had it
        # wrong, and measuring the real thing is what corrected it.
        #
        # Asserting the SHAPE rather than skipping the table: exactly one
        # assistant message per spawn, no user messages. That still catches a
        # bundle shipping somebody's conversation, and would also catch a
        # seeder that greeted twice or greeted from the wrong role.
        if c.ok("chat_messages" in tables, "chat_messages table exists"):
            rows = conn.execute(
                "SELECT role, count(*), count(DISTINCT spawn_id) FROM chat_messages GROUP BY role"
            ).fetchall()
            n_spawns = len(_factory_spawn_names())
            c.ok(
                rows == [("assistant", n_spawns, n_spawns)],
                "chat holds exactly one greeting per spawn and nothing else",
                f"got {rows}, expected [('assistant', {n_spawns}, {n_spawns})]",
            )

        # ---- and what it SHOULD have ----------------------------------
        if c.ok("spawns" in tables, "spawns table exists"):
            got = {r[0] for r in conn.execute("SELECT name FROM spawns")}
            want_spawns = _factory_spawn_names()
            c.ok(got == want_spawns, "exactly the factory spawns were seeded",
                 f"missing={sorted(want_spawns - got)} extra={sorted(got - want_spawns)}")
    finally:
        conn.close()

    # ---- auth is ENFORCED, and the shell can hold the key --------------
    # A desktop build must not run open: 127.0.0.1 is reachable by every
    # process on the machine, and this server holds the brain and BYOK keys.
    # Three sides, because any one alone can lie:
    #   the token file exists (the shell's ONLY way to learn the token),
    #   a privileged endpoint refuses without it (auth is really on),
    #   and accepts with it (the persisted token is the real credential —
    #   a gate that rejects everything would pass the middle check too).
    token_path = appsup / "api_token"
    if c.ok(token_path.is_file(), "an api_token was minted on first run"):
        mode = token_path.stat().st_mode & 0o777
        c.ok(mode == 0o600, "api_token is owner-only", f"mode is {oct(mode)}")
        token = token_path.read_text().strip()

        def _status(headers: dict) -> int:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/v1/spawns", headers=headers
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code

        anon = _status({})
        c.ok(anon in (401, 403), "a privileged endpoint refuses without the token",
             f"anonymous GET /api/v1/spawns returned {anon}")
        authed = _status({"Authorization": f"Bearer {token}"})
        c.ok(authed == 200, "the persisted token is accepted",
             f"authed GET /api/v1/spawns returned {authed}")

    # ---- the chat transport actually holds a WebSocket ------------------
    # THE BUG THIS CATCHES (0.1.0-0.1.6, found 2026-07-27): `websockets` sat in
    # the `dev` extra, so no release build installed it, and PyInstaller could
    # not see it either because uvicorn imports it lazily by name. uvicorn then
    # logs "No supported WebSocket library detected" and serves every /ws/
    # upgrade as a plain HTTP request, which the SPA catch-all answers 200. The
    # server passed /health, passed auth, passed every check in this file — and
    # chat had never worked in any packaged build. Only a real handshake against
    # the real bundle can tell the difference, so do that.
    def _ws_status(query: str) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", f"/ws/arslan/acceptance-probe{query}", headers={
                "Connection": "Upgrade",
                "Upgrade": "websocket",
                "Sec-WebSocket-Version": "13",
                "Sec-WebSocket-Key": base64.b64encode(b"0123456789abcdef").decode(),
            })
            return conn.getresponse().status
        except Exception as exc:  # noqa: BLE001 — a failed probe is a failed check
            print(f"    (websocket probe raised {type(exc).__name__}: {exc})")
            return -1
        finally:
            conn.close()

    if token:
        upgraded = _ws_status(f"?token={token}")
        # 101 = upgraded. 200 is the specific corpse of this bug: the SPA
        # catch-all answering an upgrade the server could not perform.
        c.ok(upgraded == 101, "the bundle can hold a WebSocket (chat transport)",
             f"authenticated /ws/ upgrade returned {upgraded}"
             + (" — this is the SPA catch-all: uvicorn has no WebSocket library"
                if upgraded == 200 else ""))
        # Discrimination: a 101 that ignores auth would also pass the line above
        # while meaning something much worse.
        anon_ws = _ws_status("")
        c.ok(anon_ws in (401, 403), "the WebSocket refuses an unauthenticated handshake",
             f"anonymous /ws/ upgrade returned {anon_ws}")

    # ---- a clean boot says nothing alarming ---------------------------
    text = log.read_text(errors="replace")
    errors = [
        ln for ln in text.splitlines()
        if ("ERROR" in ln or "Traceback" in ln)
        # uvicorn logs 4xx at ERROR in some configs; those are not boot errors.
        and "404" not in ln
    ]
    c.ok(not errors, "no errors in the boot log", " | ".join(errors[:3]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("app", type=pathlib.Path)
    args = ap.parse_args()
    app = args.app.resolve()
    if not (app / "Contents/MacOS/arslan-desktop").is_file():
        raise SystemExit(f"{app} does not look like a built Arslan.app")

    c = Checks()
    print(f"==> checking {app.name}")
    check_bundle_contents(app, c)

    home = pathlib.Path(tempfile.mkdtemp(prefix="arslan-fresh-"))
    proc = None
    try:
        proc, port, log = boot(app, home)
        print(f"    booted on port {port} with HOME={home}")
        check_runtime(port, home, log, c)
    finally:
        if proc is not None:
            proc.kill()
            proc.wait(timeout=20)
        shutil.rmtree(home, ignore_errors=True)

    return c.report()


if __name__ == "__main__":
    raise SystemExit(main())
