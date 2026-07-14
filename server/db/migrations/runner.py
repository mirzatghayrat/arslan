"""Explicit, versioned migration runner — the single ordered source of truth.

Formalizes the previously hand-wired boot chain. Each migration exposes an
idempotent ``upgrade_sync(conn)``; we record applied ids in ``schema_version`` so
an install re-applies only the pending tail. VERBATIM order from the old main.py
chain (do not reorder). See
docs/superpowers/plans/2026-07-14-migration-runner-impl-plan.md.

Canonical chain (from the old ``main.py`` boot block, verbatim, in order):
``0006 … 0031`` — 26 entries. It starts at ``0006``, not ``0001``:
``0001``–``0005`` predate ``Base.metadata.create_all`` (the alembic era) and are
now create_all-subsumed, so they are NOT in the boot chain and NOT registered
here (they still define ``upgrade_sync`` — the completeness test allow-lists them
as SUBSUMED). The two data-writing migrations (``0006``, ``0018``) are
idempotency-guarded, so the whole chain is a safe net no-op re-run on an existing
install.

🔴 MAINTAINER: adding a migration (e.g. 0032) requires updating THREE places in
lockstep — the version file under versions/, ``MIGRATIONS`` here, and the
hardcoded id list in ``test_registry_matches_boot_chain_verbatim`` — a mismatch
is a deliberate CI red, not a bug to be worked around.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import sqlalchemy as sa

from .versions._0006_provider_configs import upgrade_sync as _m0006
from .versions._0007_runs import upgrade_sync as _m0007
from .versions._0008_evolution_proposals import upgrade_sync as _m0008
from .versions._0009_knowledge import upgrade_sync as _m0009
from .versions._0010_mcp_servers import upgrade_sync as _m0010
from .versions._0011_mcp_http_host import upgrade_sync as _m0011
from .versions._0012_discovery_candidates import upgrade_sync as _m0012
from .versions._0013_distilled_sessions import upgrade_sync as _m0013
from .versions._0014_chat_archived import upgrade_sync as _m0014
from .versions._0015_persona_seeds import upgrade_sync as _m0015
from .versions._0016_spawn_is_default import upgrade_sync as _m0016
from .versions._0017_skill_candidates import upgrade_sync as _m0017
from .versions._0018_second_brain import upgrade_sync as _m0018
from .versions._0019_fact_category import upgrade_sync as _m0019
from .versions._0020_fact_label import upgrade_sync as _m0020
from .versions._0021_run_detail import upgrade_sync as _m0021
from .versions._0022_run_created_idx import upgrade_sync as _m0022
from .versions._0023_run_kb_sources import upgrade_sync as _m0023
from .versions._0024_conversation_events import upgrade_sync as _m0024
from .versions._0025_second_brain_rebuild import upgrade_sync as _m0025
from .versions._0026_notes import upgrade_sync as _m0026
from .versions._0027_mcp_health import upgrade_sync as _m0027
from .versions._0028_evolution_real import upgrade_sync as _m0028
from .versions._0029_usage_ledger import upgrade_sync as _m0029
from .versions._0030_scheduled_tasks import upgrade_sync as _m0030
from .versions._0031_model_catalog import upgrade_sync as _m0031

# VERBATIM order from the old main.py boot chain — do NOT reorder/add/drop.
MIGRATIONS: list[tuple[str, Callable]] = [
    ("0006", _m0006),
    ("0007", _m0007),
    ("0008", _m0008),
    ("0009", _m0009),
    ("0010", _m0010),
    ("0011", _m0011),
    ("0012", _m0012),
    ("0013", _m0013),
    ("0014", _m0014),
    ("0015", _m0015),
    ("0016", _m0016),
    ("0017", _m0017),
    ("0018", _m0018),
    ("0019", _m0019),
    ("0020", _m0020),
    ("0021", _m0021),
    ("0022", _m0022),
    ("0023", _m0023),
    ("0024", _m0024),
    ("0025", _m0025),
    ("0026", _m0026),
    ("0027", _m0027),
    ("0028", _m0028),
    ("0029", _m0029),
    ("0030", _m0030),
    ("0031", _m0031),
]


def _ensure_table(conn) -> None:
    conn.execute(sa.text(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"))


def current_versions(conn) -> set[str]:
    _ensure_table(conn)
    return set(conn.execute(sa.text("SELECT version FROM schema_version")).scalars().all())


def head() -> str:
    return MIGRATIONS[-1][0]


def apply_pending(conn) -> list[str]:
    """Idempotent: apply every registered migration whose id isn't recorded, in
    order, recording each. Runs under the caller's transaction (matches boot's
    single ``begin()``)."""
    applied = current_versions(conn)
    done: list[str] = []
    for vid, fn in MIGRATIONS:
        if vid in applied:
            continue
        fn(conn)
        conn.execute(sa.text("INSERT INTO schema_version(version, applied_at) VALUES (:v, :t)"),
                     {"v": vid, "t": datetime.utcnow().isoformat()})
        done.append(vid)
    return done


def main(argv: list[str] | None = None) -> int:
    """CLI: bring the configured SQLite DB up to head via a standalone SYNC engine.

    Mirrors boot's DB-prep exactly — ``Base.metadata.create_all`` then
    ``apply_pending`` in ONE transaction — because the migrations ALTER tables that
    ``create_all`` builds (a bare ``apply_pending`` on an empty file fails), so the
    two must run together for this to work on a fresh DB. Uses a sync
    ``create_engine`` so it runs with no event loop. ``--db PATH`` overrides the
    location; otherwise the app's configured ``db_path`` is used.
    """
    import argparse
    from pathlib import Path

    from sqlalchemy import create_engine

    from server.db.models import Base

    parser = argparse.ArgumentParser(
        prog="python -m server.db.migrations.runner",
        description="Apply pending Arslan DB migrations (bring the DB up to head).",
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help="SQLite DB file path (default: the app's configured db_path).",
    )
    args = parser.parse_args(argv)

    if args.db_path is None:
        from server.config import load_settings

        db_path = load_settings().db_path
    else:
        db_path = args.db_path

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            pending = [vid for vid, _ in MIGRATIONS if vid not in current_versions(conn)]
            print(f"db:      {db_path}")
            print(f"head:    {head()}")
            print(f"pending: {' '.join(pending) if pending else '(none)'}")
            applied = apply_pending(conn)
        print(f"applied: {' '.join(applied) if applied else '(none)'}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
