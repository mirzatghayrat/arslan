"""0103 (v0.1.64 C7c-5c): the experts' data moves to what replaced them, then the expert-era tables go.

One migration in the boot transaction (foreign keys on), each step guarded by what the database has, so a crash
leaves nothing half done and a second run changes nothing. The runner's upgrade backup, taken before any pending
migration, holds the dropped rows until it is pruned (only the newest three are kept). A new install has none of
these tables: every step is a no-op there except the expert-scope triggers (step 8).

0. An install whose memory v2 never activated maps its legacy memory first (memory_migration, as 0047 does), so
   the experts' stored preferences are not lost with `spawns`.
1. Each expert the user made (`is_default = 0`; the built-in examples seeded until 0.1.48 are not theirs) becomes a skill, written as `skill_forge.register` wrote
   it for `expert_conversion.convert` (category "authored", tier safe), from frozen copies of that code
   (the 0077 and 0082 rule: no async service in a migration, and a later change there never changes this). A
   taken key is never overwritten: the same body means already converted; otherwise `key-2`, `key-3`, ... A
   prompt too short to be a method is counted, not converted. Every converted skill is written switched off
   (enabled = 0), its description saying it came from a former expert and is off until the user switches it on:
   the credential screen misses many secrets (cloud keys, URLs with a password, Basic auth, JWTs, a secret split
   by a line break), so no prompt is trusted to be free of one (⓪Plan's ruling, review of C7c-5c). Where the screen
   does find one, it is also replaced (content_policy.without_credentials) and the method opens with a note that a
   secret was removed and must be added back: never skipped, never verbatim (⓪Plan's ruling, Q4).
2. Knowledge an expert held privately moves into one "Former expert notes" collection, bound to no project
   (so retrieval sees it no more than before), the expert's name in `origin_label` (with any credential the screen
   finds replaced, as in step 1). One UPDATE sets
   collection_id and clears spawn_id, so ck_chunk_exactly_one_scope holds; ids, FTS rows and embeddings stay.
3. An expert's stored answer (`spawn_summary`) becomes an `arslan` reply: the display copy keeps the words, the
   context copy says it was relayed (what the answer prompt added at read time until now).
4. Every remaining pointer to `spawns` is cleared (runs, scheduled tasks, messages; `runs.spawn_name` stays).
5. A task an expert drove and that has not finished is cancelled, as TaskRepository.cancel does, with the reason
   `task_invalid_driver` (the web's "cannot resume"; task_service refuses that driver already).
6. Every expert-scope memory entry moves to global with its id kept (a restored backup is reconciled by id).
   Deleted: the scope only. Superseded: moved, still superseded. Restricted (secret, never-use, or no content):
   quarantined. Already present (a live global entry has the same dedup key, as MemoryRepository computes it for
   that entry's words in global scope): superseded by that entry, with no proposal, since accepting it could only
   collide with that entry's key. Every other: proposed, with a pending `memory_v2` proposal (candidate NULL) and a `migration`
   source, its confirmation cleared, so only the user's yes on that proposal puts it in use; never the bulk
   "noticed earlier" accept. Their stale pending proposals are dismissed, and so are v1 proposals on `spawns`.
   No tombstone is written and `deletion_epoch` is not touched; old tombstones keep scope "expert", which the
   deletion manifest still accepts. One `memory_migration_reports` row holds the counts, never content.
7. The tables drop, children first (their indexes and triggers with them). `distilled_sessions` stays: it is
   not expert-only (deleting a conversation purges it).
8. On an upgraded install, `runs`, `scheduled_tasks`, `arslan_messages` and `knowledge_chunks` were made with
   `REFERENCES spawns`; with foreign keys on, a write to any of them fails once `spawns` is gone, and the boot
   transaction cannot rebuild them (foreign_keys cannot be switched off inside it, and rebuilding `runs` would
   cascade-delete its steps). So where any CREATE text still names `spawns`, an empty `spawns(id)` stub is
   left: nothing ever writes it, so a non-NULL spawn_id can never be stored again. A new install gets none.
   Drop the stub in a later release once no CREATE text references spawns (⓪Plan's ruling, Q3).
   Then two triggers refuse the expert scope on memory_entries, in place of rebuilding ck_memory_scope (whose
   table cannot be rebuilt either); the model's CHECK drops "expert" for new installs.

`chat_messages` and `feedback` (the old one-to-one expert chats) drop without an export
(the user's decision, 2026-11-15); the upgrade backup keeps them until it is pruned.

Order with 0102: 0102 (another lane) may merge after this one. The runner applies every listed id missing from
`schema_version` (a set, since 0073), so list 0102 before 0103 and an install that already has 0103 still gets 0102.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
import uuid
from collections import Counter
from datetime import datetime

# Frozen in 0082 (`untrusted.clean_name` as of v0.1.64); a migration may import another's frozen helper (0069).
from ._0082_clean_stored_names import _clean


RELAYED_PREFIX = "(relayed output from a former expert) "
COLLECTION_NAME = "Former expert notes"
COLLECTION_DESCRIPTION = "Notes from removed experts; bind to a project to use them"
REASON = "expert_scope_retired"
SECRET_NOTE = ("> A secret (a password, key or token) was removed from this method when the expert became a skill, "
               "and the skill was switched off. Add it back where it is needed before you switch the skill on.\n\n")

#: Step 7, children before parents.
DROPPED = ("spawn_capabilities", "conversation_spawns", "spawn_collections", "spawn_phases", "chat_messages",
           "feedback", "evolution_attempts", "evolution_proposals", "synthetic_tasks",
           "persona_seeds_fts", "persona_seeds", "recipe_executions", "recipe_versions", "spawns")
TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS memory_entries_scope_retired_ins BEFORE INSERT ON memory_entries "
    "WHEN NEW.scope_kind = 'expert' BEGIN SELECT RAISE(ABORT, 'memory_scope_retired'); END",
    "CREATE TRIGGER IF NOT EXISTS memory_entries_scope_retired_upd BEFORE UPDATE OF scope_kind ON memory_entries "
    "WHEN NEW.scope_kind = 'expert' BEGIN SELECT RAISE(ABORT, 'memory_scope_retired'); END",
)

OFF_NOTE = "Converted from a former expert; off until you switch it on."

# --- frozen from skill_forge (MAX_SKILL_BYTES, validate) and expert_conversion (skill_key, skill_body), v0.1.64 ---
_MAX_SKILL_BYTES = 15 * 1024
_MIN_BODY_CHARS = 80
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_KEY_MAX = 60


def _skill_key(spawn_id, name) -> str:
    ascii_name = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]
    return f"expert-{spawn_id}" + (f"-{ascii_name}" if ascii_name else "")


def _skill_body(row: dict, note: str = "") -> str:
    domain = " / ".join(x for x in (row["domain_category"], row["domain_subcategory"]) if x)
    role = f" The work of a {row['persona_role']}." if row["persona_role"] else ""
    head = f"# {row['name']}\n\n## Trigger\nUse for work in {domain or 'this area'}.{role}\n\n## Method\n{note}"
    room = _MAX_SKILL_BYTES - len(head.encode()) - 64
    method = (row["system_prompt"] or "").strip().encode()[:room].decode(errors="ignore")
    return head + method + "\n"


def _invalid(key: str, name: str, description: str, body: str) -> bool:
    return (not _KEY_RE.match(key) or not name.strip() or not description.strip() or "## Trigger" not in body
            or len(body) < _MIN_BODY_CHARS or len(body.encode("utf-8")) > _MAX_SKILL_BYTES)


# --- frozen from memory_repository (digest, _dedup_key) and content_policy.normalized_memory, v0.1.64 ---
def _dedup_key(digest_key: str, owner_id: str, kind: str, content: str) -> str:
    """The key MemoryRepository.revise would give these words in global scope (its unique dedup_key)."""
    normalized = " ".join(unicodedata.normalize("NFKC", content).casefold().split())
    digest = hmac.new(bytes.fromhex(digest_key), normalized.encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(json.dumps([owner_id, kind, "global", None, digest]).encode()).hexdigest()


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")      # as SQLAlchemy's DateTime stores it


def _tables(connection) -> set[str]:
    return {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def _expert_names(connection, tables) -> dict[int, str]:
    if not {"id", "name"} <= _columns(connection, "spawns"):
        return {}
    return {sid: name for sid, name in connection.exec_driver_sql("SELECT id, name FROM spawns")}


def _legacy_memory(connection, tables) -> None:
    """Step 0."""
    if "memory_facts" not in _columns(connection, "spawns"):
        return
    phase = (connection.exec_driver_sql("SELECT phase FROM memory_store_state WHERE id=1").scalar()
             if "memory_store_state" in tables else None)
    if phase != "active":
        from server.services.memory_migration import migrate_legacy_sync
        migrate_legacy_sync(connection)


def _skills(connection, tables, counts) -> None:
    """Step 1."""
    from arslan.companion.content_policy import contains_credential, without_credentials
    if not {"id", "name", "system_prompt", "is_default"} <= _columns(connection, "spawns") or "skill_packs" not in tables:
        return
    where = " WHERE is_default = 0"   # only the experts the user made, as the former-experts page listed them
    rows = connection.exec_driver_sql(
        "SELECT id, name, domain_category, domain_subcategory, persona_role, system_prompt FROM spawns"
        f"{where} ORDER BY id").mappings().all()
    for raw in rows:
        row = dict(raw)
        note, held = "", False
        if any(contains_credential(str(value)) for value in row.values() if isinstance(value, str)):
            row = {k: without_credentials(v) if isinstance(v, str) else v for k, v in row.items()}
            note, held = SECRET_NOTE, True
        body = _skill_body(row, note)
        if contains_credential(body):        # what the screen still finds after the replacement: not kept at all
            body = _skill_body({**row, "system_prompt": ""}, note)
        name = _clean(row["name"], 100)
        description = _clean(f"Method from the former expert {row['name']}"[:200] + f". {OFF_NOTE}", 2000)
        base = _skill_key(row["id"], row["name"])
        if _invalid(base, name or base, description, body) or any(map(contains_credential, (body, name, description))):
            counts["skills_too_short"] += 1
            continue
        for n in range(1, 1000):
            suffix = "" if n == 1 else f"-{n}"
            key = base[:_KEY_MAX - len(suffix)].rstrip("-") + suffix
            taken = connection.exec_driver_sql("SELECT body FROM skill_packs WHERE key = ?", (key,)).first()
            if taken is None:
                connection.exec_driver_sql(
                    "INSERT INTO skill_packs (key, name, category, description, tier, status, body, enabled, "
                    "source_id) VALUES (?, ?, 'authored', ?, 'safe', 'registered', ?, 0, NULL)",
                    (key, name or key, description, body))     # always off: see the docstring, step 1
                counts["skills_made"] += 1
                counts["skills_held_off_credential"] += held
                break
            if taken[0] == body:
                counts["skills_already"] += 1
                break


def _knowledge(connection, tables, names, counts, now) -> None:
    """Step 2."""
    from arslan.companion.content_policy import contains_credential, without_credentials
    if "knowledge_chunks" not in tables:
        return
    if "origin_label" not in _columns(connection, "knowledge_chunks"):
        connection.exec_driver_sql("ALTER TABLE knowledge_chunks ADD COLUMN origin_label VARCHAR(100)")
    spawn_ids = [sid for (sid,) in connection.exec_driver_sql(
        "SELECT DISTINCT spawn_id FROM knowledge_chunks WHERE spawn_id IS NOT NULL ORDER BY spawn_id")]
    if not spawn_ids:
        return
    collection = connection.exec_driver_sql(
        "INSERT INTO collections (name, description, created_at) VALUES (?, ?, ?) RETURNING id",
        (COLLECTION_NAME, COLLECTION_DESCRIPTION, now)).scalar()
    for sid in spawn_ids:
        label = _clean(without_credentials(names.get(sid) or ""), 100)
        if not label or contains_credential(label):
            label = f"Expert {sid}"
        moved = connection.exec_driver_sql(
            "UPDATE knowledge_chunks SET collection_id = ?, origin_label = ?, spawn_id = NULL WHERE spawn_id = ?",
            (collection, label, sid))
        counts["chunks_moved"] += moved.rowcount


def _messages(connection, tables, counts) -> None:
    """Step 3."""
    if "arslan_messages" not in tables:
        return
    converted = connection.exec_driver_sql(
        "UPDATE arslan_messages SET display_content = COALESCE(display_content, content), "
        "content = ? || content, role = 'arslan' WHERE role = 'spawn_summary'", (RELAYED_PREFIX,))
    counts["messages_converted"] += converted.rowcount


def _pointers(connection, tables) -> None:
    """Step 4: every column still pointing at `spawns` (each table whose CREATE text names it), then the three the
    models keep, whatever their CREATE text says."""
    referencing = {name for (name,) in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND (sql LIKE '%REFERENCES spawns%' "
        "OR sql LIKE '%REFERENCES \"spawns\"%')")}
    for table in sorted((referencing | {"runs", "scheduled_tasks", "arslan_messages"}) - set(DROPPED)):
        if table in tables and "spawn_id" in _columns(connection, table):
            connection.exec_driver_sql(f"UPDATE {table} SET spawn_id = NULL WHERE spawn_id IS NOT NULL")


def _tasks(connection, tables, counts, now) -> None:
    """Step 5, as TaskRepository.cancel: the task, its event, its current attempt, its unfinished actions."""
    if "companion_tasks" not in tables:
        return
    rows = connection.exec_driver_sql(
        "SELECT id, attempt_id, sequence, spec_revision FROM companion_tasks "
        "WHERE json_extract(privacy, '$.driver.kind') = 'expert' "
        "AND phase NOT IN ('succeeded', 'failed', 'cancelled') ORDER BY id").all()
    for task_id, attempt_id, sequence, spec_revision in rows:
        connection.exec_driver_sql(
            "UPDATE companion_tasks SET phase = 'cancelled', cancel_requested = 1, pause_reason = 'task_invalid_driver', "
            "version = version + 1, sequence = ?, updated_at = ? WHERE id = ?", (sequence + 1, now, task_id))
        connection.exec_driver_sql(
            "INSERT INTO task_events (task_id, sequence, attempt_id, kind, payload, created_at) "
            "VALUES (?, ?, ?, 'cancel_requested', ?, ?)",
            (task_id, sequence + 1, attempt_id, json.dumps({"phase": "cancelled", "spec_revision": spec_revision}), now))
        connection.exec_driver_sql(
            "UPDATE task_attempts SET status = 'cancelled', ended_at = ? WHERE id = ?", (now, attempt_id))
        if "task_actions" in tables:
            connection.exec_driver_sql(
                "UPDATE task_actions SET status = 'uncertain', version = version + 1, updated_at = ? "
                "WHERE task_id = ? AND status IN ('prepared', 'in_flight')", (now, task_id))
        counts["tasks_ended"] += 1


def _memory(connection, tables, counts, now) -> None:
    """Step 6."""
    if "memory_entries" not in tables:
        return
    rows = connection.exec_driver_sql(
        "SELECT e.id, e.status, e.version, e.sensitivity, e.use_policy, e.scope_id, r.content, r.structured_value, "
        "e.owner_id, e.kind "
        "FROM memory_entries e LEFT JOIN memory_revisions r ON r.id = e.current_revision_id AND r.entry_id = e.id "
        "WHERE e.scope_kind = 'expert' ORDER BY e.id").all()
    digest_key = (connection.exec_driver_sql("SELECT digest_key FROM memory_store_state WHERE id=1").scalar()
                  if rows and "memory_store_state" in tables else None)
    for entry_id, status, version, sensitivity, use_policy, scope_id, content, structured, owner_id, kind in rows:
        counts["proposals_dismissed"] += connection.exec_driver_sql(
            "UPDATE memory_proposals SET status = 'dismissed', candidate = NULL, reason = ?, resolved_at = ? "
            "WHERE target_entry_id = ? AND status = 'pending'", (REASON, now, entry_id)).rowcount
        counts["entries_moved"] += 1
        if status == "deleted":
            connection.exec_driver_sql(
                "UPDATE memory_entries SET scope_kind = 'global', scope_id = NULL WHERE id = ?", (entry_id,))
            counts["entries_deleted"] += 1
            continue
        restricted = sensitivity == "secret" or use_policy == "never" or content is None
        new_status = "superseded" if status == "superseded" else ("quarantined" if restricted else "proposed")
        present = None
        if new_status == "proposed" and digest_key:
            # A live global entry already says these words: accepting this one would take its unique dedup_key.
            present = connection.exec_driver_sql(
                "SELECT id FROM memory_entries WHERE dedup_key = ? AND id != ? AND status != 'deleted' LIMIT 1",
                (_dedup_key(digest_key, owner_id, kind, content), entry_id)).scalar()
            if present is not None:
                new_status = "superseded"
        revision = str(uuid.uuid4())
        connection.exec_driver_sql(
            "INSERT INTO memory_revisions (id, entry_id, version, content, structured_value, previous_version, "
            "change_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (revision, entry_id, version + 1, content, structured, version, REASON, now))
        connection.exec_driver_sql(
            "INSERT INTO memory_sources (id, entry_id, revision_id, source_kind, source_ref, author, created_at) "
            "VALUES (?, ?, ?, 'migration', ?, 'system', ?)",
            (str(uuid.uuid4()), entry_id, revision,
             json.dumps({"migration": "0103", "from_scope": "expert", "from_scope_id": scope_id}), now))
        connection.exec_driver_sql(
            "UPDATE memory_entries SET scope_kind = 'global', scope_id = NULL, status = ?, version = ?, "
            "current_revision_id = ?, dedup_key = NULL, confirmed_at = NULL, confirmation_kind = NULL, updated_at = ?, "
            "superseded_by = COALESCE(?, superseded_by) "
            "WHERE id = ?", (new_status, version + 1, revision, now, present, entry_id))
        if present is not None:
            counts["already_present"] += 1
        elif new_status == "proposed":
            connection.exec_driver_sql(
                "INSERT INTO memory_proposals (kind, table_name, old_id, new_id, target_entry_id, target_version, "
                "candidate, reason, status, provenance, conversation_id, created_at) "
                "VALUES ('memory_v2', 'memory_entries', NULL, NULL, ?, ?, NULL, ?, 'pending', ?, NULL, ?)",
                (entry_id, version + 1, REASON, json.dumps({"source_kind": "migration"}), now))
            counts["entries_proposed"] += 1
        elif new_status == "quarantined":
            counts["entries_restricted"] += 1
        else:
            counts["entries_superseded"] += 1
    if "memory_proposals" in tables:
        # v1 suggestions about an expert's preferences: accepting one would write to `spawns` (brain.py).
        dismissed = connection.exec_driver_sql(
            "UPDATE memory_proposals SET status = 'dismissed', resolved_at = ? "
            "WHERE table_name = 'spawns' AND status = 'pending' AND kind != 'memory_v2'", (now,))
        counts["v1_proposals_dismissed"] += dismissed.rowcount


def _drop(connection, tables, counts) -> None:
    """Step 7."""
    for table in ("chat_messages", "feedback"):
        if table in tables:
            counts[f"{table}_dropped"] += connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar()
    for table in DROPPED:
        connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")


def _stub_and_guard(connection, tables) -> None:
    """Step 8."""
    still = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name != 'spawns' AND (sql LIKE '%REFERENCES spawns%' "
        "OR sql LIKE '%REFERENCES \"spawns\"%') LIMIT 1").first()
    if still is not None:
        # Empty forever: it only keeps the tables made with `REFERENCES spawns` writable (see the docstring).
        # DELETE-BY: a later release, once no CREATE text references spawns.
        connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS spawns (id INTEGER PRIMARY KEY)")
    if "memory_entries" in tables:
        for statement in TRIGGERS:
            connection.exec_driver_sql(statement)


def upgrade_sync(connection) -> None:
    tables = _tables(connection)
    counts: Counter = Counter()
    now = _now()
    _legacy_memory(connection, tables)
    tables = _tables(connection)
    names = _expert_names(connection, tables)
    _skills(connection, tables, counts)
    _knowledge(connection, tables, names, counts, now)
    _messages(connection, tables, counts)
    _pointers(connection, tables)
    _tasks(connection, tables, counts, now)
    _memory(connection, tables, counts, now)
    _drop(connection, tables, counts)
    _stub_and_guard(connection, _tables(connection))
    if any(counts.values()) and "memory_migration_reports" in tables:
        # Counts only, never content (memory_migration's report table, as 0047 writes it).
        connection.exec_driver_sql(
            "INSERT INTO memory_migration_reports (source_version, summary, created_at) VALUES ('0103', ?, ?)",
            (json.dumps(dict(sorted(counts.items()))), now))


def downgrade_sync(connection) -> None:
    """Nothing to restore: the dropped rows are in the upgrade backup while it is kept."""
    return

