"""0103 (v0.1.64 C7c-5c): the experts' data moves, then the expert-era tables go (C7c-5-design.md §1, §8).

Booted the way the app boots (storage_boot.initialize on build_engine, foreign keys on), so the constraint that
shaped the design (no table rebuild with foreign keys on) is exercised. The pre-0103 shape comes from the frozen
CREATE text in tests/server/fixtures/pre_0103_expert_tables.sql (tests/server/pre_0103.py): the models cannot
make it any more. Every value here is synthetic.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from arslan.companion.content_policy import normalized_memory
from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite
from server.db import session as db_session
from server.db.migrations import runner
from server.db.migrations.versions import _0103_retire_experts as m0103
from server.db.session import build_engine
from server.services import memory_deletion_manifest as manifest
from server.services import storage_boot
from server.services.memory_repository import repository
from tests.server import pre_0103

SECRET = "SyntheticOnlyValue42"
LONG = "Compare the options side by side, cite each source, and end with one recommendation. " * 2
NOW = "2026-11-01 09:00:00.000000"
USER = MemoryActor(origin="user")
DROPPED = set(m0103.DROPPED)
# Entry ids (uuid-shaped, as memory_deletion_manifest requires).
P1, P2, A1, Z1, S_OLD, S_NEW, D1, R1, ST1 = (f"00000000-0000-4000-8000-0000000000{n:02d}" for n in range(1, 10))


async def _boot(db_path) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()


def _rows(db_path, query, params=()) -> list[tuple]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.exec_driver_sql(query, params)]
    finally:
        engine.dispose()


def _write(db_path, statements) -> None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            for statement, params in statements:
                conn.exec_driver_sql(statement, params)
    finally:
        engine.dispose()


def _tables(db_path) -> set[str]:
    return {name for (name,) in _rows(db_path, "SELECT name FROM sqlite_master WHERE type='table'")}


def _spawn(sid, name, prompt, *, default=0, facts=()):
    return ("INSERT INTO spawns (id, name, domain_category, system_prompt, is_default, memory_facts) "
            "VALUES (?, ?, 'research', ?, ?, ?)", (sid, name, prompt, default, json.dumps(list(facts))))


def _digest(key: str, content: str) -> str:
    return hmac.new(bytes.fromhex(key), normalized_memory(content).encode(), hashlib.sha256).hexdigest()


def _entry(entry_id, status, content, *, key, sensitivity="normal", use_policy="local_only", confirmation=None,
           superseded_by=None, source="worker"):
    """An expert-scope entry (scope id "2") at version 1, its revision and one source, as old data."""
    revision = entry_id[:-2] + "r" + entry_id[-1]
    return [
        ("INSERT INTO memory_revisions (id, entry_id, version, content, structured_value, previous_version, "
         "change_reason, created_at) VALUES (?, ?, 1, ?, '{}', NULL, 'created', ?)", (revision, entry_id, content, NOW)),
        ("INSERT INTO memory_entries (id, owner_id, kind, scope_kind, scope_id, status, current_revision_id, "
         "normalized_hash, dedup_key, version, sensitivity, use_policy, confirmation_kind, confirmed_at, superseded_by, "
         "created_at, updated_at) VALUES (?, 'local', 'preference', 'expert', '2', ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
         (entry_id, status, revision, _digest(key, content) if content else None, "dedup-" + entry_id, sensitivity,
          use_policy, confirmation, NOW if confirmation else None, superseded_by, NOW, NOW)),
        ("INSERT INTO memory_sources (id, entry_id, revision_id, source_kind, source_ref, author, created_at) "
         "VALUES (?, ?, ?, ?, '{\"conversation_id\": \"c1\"}', 'assistant', ?)",
         (entry_id[:-2] + "s" + entry_id[-1], entry_id, revision, source, NOW)),
    ]


EDITOR = {"name": "Editor", "domain_category": "research", "domain_subcategory": None, "persona_role": None,
          "system_prompt": "Edit for clarity. " + LONG}


async def _before_0103(db_path) -> dict:
    """A user-shaped install from before C7c-5c (design §8.1): 6 user experts and 1 built-in, a private knowledge
    chunk, two relayed answers, an expert-driven task, expert-scope memory of every kind, a v1 proposal on spawns,
    the old chats, and a run and a scheduled task with children."""
    await _boot(db_path)
    pre_0103.restore_child_tables(db_path)
    key = _rows(db_path, "SELECT digest_key FROM memory_store_state")[0][0]
    collision = m0103._skill_key(6, "Writer")
    same = m0103._skill_key(7, "Editor")
    statements = [("PRAGMA foreign_keys=OFF", ())]
    statements += [(s, ()) for s in pre_0103.statements("tables")]
    statements += [
        _spawn(1, "Seeded example", LONG, default=1),
        _spawn(2, "Research Analyst", "You research local speech models. " + LONG),
        _spawn(3, "研究助手", "你负责调研。" + LONG),
        _spawn(4, "Tiny", "hi"),
        _spawn(5, "Deploy helper", f"Deploy the site. The password: {SECRET} is for staging. " + LONG),
        _spawn(6, "Writer", "Write in short sentences. " + LONG),
        _spawn(7, "Editor", "Edit for clarity. " + LONG),
        # A hand-made skill that took expert 6's key, and expert 7 converted before (same body).
        ("INSERT INTO skill_packs (key, name, category, description, tier, status, body, enabled) "
         "VALUES (?, 'Mine', 'authored', 'my own', 'safe', 'registered', ?, 1)",
         (collision, "# Mine\n\n## Trigger\nMine.\n\n## Method\n" + "x" * 80)),
        ("INSERT INTO collections (id, name) VALUES (9, 'Kept')", ()),
        ("INSERT INTO knowledge_chunks (id, spawn_id, collection_id, source, chunk_index, text, embedding, "
         "embedding_model) VALUES (41, 2, NULL, 'notes.md', 0, 'Synthetic speech model notes', X'0000803F', 'm')", ()),
        ("INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (41, 'Synthetic speech model notes')", ()),
        ("INSERT INTO runs (id, conversation_id, spawn_id, spawn_name, user_message, started_at, task_tokens, status, "
         "tokens_estimated) VALUES (11, 'c1', 2, 'Research Analyst', 'hi', ?, 0, 'done', 0)", (NOW,)),
        ("INSERT INTO run_steps (run_id, seq, kind) VALUES (11, 0, 'tool_call')", ()),
        ("INSERT INTO run_evaluations (run_id, dimension, status, score, comment) VALUES (11, 'routing', 'pass', 9, '')",
         ()),
        ("INSERT INTO scheduled_tasks (id, name, prompt, spawn_id, target, schedule_kind, interval_s, enabled, "
         "consecutive_failures) VALUES (12, 't', 'p', 2, 'spawn', 'interval', 3600, 1, 0)", ()),
        ("INSERT INTO scheduled_task_runs (task_id, outcome, run_id) VALUES (12, 'ok', 11)", ()),
        ("INSERT INTO arslan_messages (id, conversation_id, role, content, display_content, spawn_id, run_id) "
         "VALUES (21, 'c1', 'spawn_summary', '[Mermer] I am Mermer', NULL, 2, 11)", ()),
        ("INSERT INTO arslan_messages (id, conversation_id, role, content, display_content, spawn_id) "
         "VALUES (22, 'c1', 'spawn_summary', 'context copy', 'What the user saw', 2)", ()),
        ("INSERT INTO companion_tasks (id, owner_id, conversation_id, spec_revision, version, sequence, phase, "
         "attempt_id, budget, privacy, results, cancel_requested, created_at, updated_at) VALUES ('task-x', 'local', "
         "'c1', 1, 3, 4, 'waiting_user', 'att-x', '{}', '{\"driver\": {\"kind\": \"expert\", \"id\": 2}}', '[]', 0, "
         "?, ?)", (NOW, NOW)),
        ("INSERT INTO task_attempts (id, task_id, number, spec_revision, status, run_ids, started_at) "
         "VALUES ('att-x', 'task-x', 1, 1, 'running', '[]', ?)", (NOW,)),
        ("INSERT INTO chat_messages (spawn_id, role, content) VALUES (2, 'user', 'old chat')", ()),
        ("INSERT INTO feedback (spawn_id, session_id, user_action) VALUES (2, 's', 'accept')", ()),
    ]
    # Expert 7 was converted on the former-experts page before (the same body): not converted again.
    statements.append(("INSERT INTO skill_packs (key, name, category, description, tier, status, body, enabled) "
                       "VALUES (?, 'Editor', 'authored', 'd', 'safe', 'registered', ?, 1)",
                       (same, m0103._skill_body(EDITOR))))
    statements += _entry(P1, "proposed", "Prefers tables", key=key, source="extractor")
    statements += _entry(P2, "proposed", "Prefers citations", key=key)
    statements += _entry(A1, "active", "Prefers short answers", key=key, confirmation="explicit_user_request")
    statements += _entry(Z1, "paused", "Prefers bullet lists", key=key)
    statements += _entry(S_NEW, "active", "Prefers metric units", key=key, confirmation="explicit_user_request")
    statements += _entry(S_OLD, "superseded", "Prefers imperial units", key=key, superseded_by=S_NEW)
    statements += _entry(D1, "deleted", None, key=key)
    statements += _entry(R1, "quarantined", None, key=key, sensitivity="secret", use_policy="never")
    statements += _entry(ST1, "proposed", "Prefers dark mode", key=key)
    statements += [
        ("INSERT INTO memory_deletions (id, instance_id, entry_id, epoch, content_digest, scope_kind, scope_key, "
         "created_at) SELECT '00000000-0000-4000-8000-0000000000d1', instance_id, ?, 1, ?, 'expert', '2', ? "
         "FROM memory_store_state", (D1, _digest(key, "Old deleted preference"), NOW)),
        ("UPDATE memory_store_state SET deletion_epoch = 1", ()),
        ("INSERT INTO memory_proposals (kind, table_name, target_entry_id, target_version, candidate, reason, status) "
         "VALUES ('memory_v2', 'memory_entries', ?, 1, ?, 'confirmation_required', 'pending')",
         (ST1, json.dumps({"content": "Prefers dark mode", "scope": {"kind": "expert", "id": "2"}}))),
        ("INSERT INTO memory_proposals (kind, table_name, old_id, reason, status) "
         "VALUES ('append_suspect', 'spawns', 2, '', 'pending')", ()),
        ("INSERT INTO memory_legacy_map (source_table, source_key, entry_id, source_sha256, migration_note) "
         "VALUES ('spawns', '2:0', ?, 'x', 'needs_review')", (P2,)),
        ("UPDATE spawns SET memory_facts = '[\"Prefers citations\"]' WHERE id = 2", ()),
    ]
    _write(db_path, statements)
    assert _rows(db_path, "PRAGMA foreign_key_check") == []
    return {"key": key, "collision": collision, "same": same}


@pytest.fixture
async def upgraded(tmp_path, monkeypatch):
    """The install above, booted once more (0103 runs), with the app's session pointed at it."""
    db = tmp_path / "arslan.db"
    info = await _before_0103(db)
    assert "0103" not in {v for (v,) in _rows(db, "SELECT version FROM schema_version")}
    await _boot(db)
    engine = build_engine(f"sqlite+aiosqlite:///{db}")
    monkeypatch.setattr(db_session, "AsyncSessionLocal",
                        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
    yield db, info
    await engine.dispose()


def _secret_free(db_path) -> None:
    """The credential is in no table and no schema text (the dropped `spawns` held it)."""
    for (table,) in _rows(db_path, "SELECT name FROM sqlite_master WHERE type='table'"):
        for row in _rows(db_path, f'SELECT * FROM "{table}"'):
            assert SECRET not in json.dumps(row, default=repr), table


async def _upgraded_with(tmp_path, extra) -> tuple:
    """The install above plus `extra(info)` statements, booted once more (0103 runs)."""
    db = tmp_path / "arslan.db"
    info = await _before_0103(db)
    _write(db, [("PRAGMA foreign_keys=OFF", ()), *extra(info)])
    await _boot(db)
    return db, info


def _global_dedup(key: str, content: str) -> str:
    """memory_repository's dedup_key for a user's preference in global scope."""
    return hashlib.sha256(json.dumps(["local", "preference", "global", None, _digest(key, content)]).encode()).hexdigest()


# -- 1. the user-shaped database ------------------------------------------------------------------------------------

async def test_0103_is_in_the_chain_and_applied_wherever_it_sits(tmp_path):
    """Order-independent (0102, another lane's, may land before or after): 0103 is listed with its upgrade, the
    list stays sorted, and a boot records it."""
    ids = [vid for vid, _ in runner.MIGRATIONS]
    assert ids == sorted(ids) and ("0103", m0103.upgrade_sync) in runner.MIGRATIONS
    db = tmp_path / "arslan.db"
    await _boot(db)
    assert {v for (v,) in _rows(db, "SELECT version FROM schema_version")} >= {"0101", "0103"}


async def test_experts_become_skills_and_nothing_overwrites_a_taken_key(upgraded):
    db, info = upgraded
    skills = {key: (name, category, enabled, body) for key, name, category, enabled, body in _rows(
        db, "SELECT key, name, category, enabled, body FROM skill_packs WHERE key LIKE 'expert-%'")}
    assert set(skills) == {"expert-2-research-analyst", "expert-3", "expert-5-deploy-helper",
                           info["collision"] + "-2", info["collision"], m0103._skill_key(7, "Editor")}
    assert skills[info["collision"]][0] == "Mine"                      # the hand-made skill is untouched
    assert "Write in short sentences" in skills[info["collision"] + "-2"][3]
    assert skills["expert-3"][0] == "研究助手" and "你负责调研" in skills["expert-3"][3]
    assert all(category == "authored" for _, category, _, _ in skills.values())
    held = skills["expert-5-deploy-helper"]
    assert held[2] == 0 and m0103.SECRET_NOTE.strip() in held[3] and "[secret removed]" in held[3]
    assert "Deploy the site" in held[3] and SECRET not in held[3]
    made = {key: enabled for key, (_, _, enabled, _) in skills.items()
            if key not in (info["collision"], info["same"])}                   # the two that were there before
    assert made == dict.fromkeys(made, 0) and len(made) == 4                  # every converted skill is off
    descriptions = dict(_rows(db, "SELECT key, description FROM skill_packs WHERE key LIKE 'expert-%'"))
    assert descriptions["expert-2-research-analyst"] == f"Method from the former expert Research Analyst. {m0103.OFF_NOTE}"
    assert all(descriptions[key].endswith(m0103.OFF_NOTE) for key in made)
    assert not any(key.startswith("expert-4") or key.startswith("expert-1") for key in skills)   # short; built-in
    assert skills[info["same"]][0] == "Editor" and _rows(db, "SELECT description FROM skill_packs WHERE key=?",
                                                          (info["same"],)) == [("d",)]          # converted before
    _secret_free(db)


async def test_a_prompt_with_secrets_the_screen_misses_still_becomes_a_skill_that_is_off(tmp_path):
    """C7c-5c review: contains_credential finds neither a cloud access key id nor a URL with a password, so a skill
    from such a prompt must start off as well as every other. Built from parts: no secret-shaped literal here."""
    from arslan.companion.content_policy import contains_credential
    access_key = "AK" + "IA" + "SYNTHETIC" + "0000000"                       # AKIA + 16 characters
    url = "postgres" + "://" + "user:pw" + "@host/db"
    prompt = f"Run the nightly report with key {access_key} against {url}. " + LONG
    assert not contains_credential(prompt)                                   # what the screen misses
    db, _ = await _upgraded_with(tmp_path, lambda info: [_spawn(8, "Cloud helper", prompt)])
    [(enabled, description, body)] = _rows(
        db, "SELECT enabled, description, body FROM skill_packs WHERE key = ?", (m0103._skill_key(8, "Cloud helper"),))
    assert enabled == 0 and description.endswith(m0103.OFF_NOTE)
    assert m0103.SECRET_NOTE.strip() not in body                             # nothing was found, so no note


async def test_an_expert_name_holding_a_secret_is_not_kept_in_origin_label(tmp_path):
    name = f"Ops password: {SECRET}"
    db, _ = await _upgraded_with(tmp_path, lambda info: [
        _spawn(9, name, "Keep the servers patched. " + LONG),
        ("INSERT INTO knowledge_chunks (id, spawn_id, collection_id, source, chunk_index, text, embedding, "
         "embedding_model) VALUES (42, 9, NULL, 'ops.md', 0, 'Synthetic ops notes', X'0000803F', 'm')", ())])
    [(label,)] = _rows(db, "SELECT origin_label FROM knowledge_chunks WHERE id = 42")
    assert SECRET not in label and "[secret removed]" in label
    _secret_free(db)


async def test_a_moved_entry_a_global_entry_already_says_is_marked_present_not_proposed(tmp_path):
    """C7c-5c review: accepting it would take the global entry's unique dedup_key (an IntegrityError, a 500)."""
    present = "00000000-0000-4000-8000-000000000010"

    def extra(info):
        revision = present[:-2] + "r0"
        return [
            ("INSERT INTO memory_revisions (id, entry_id, version, content, structured_value, previous_version, "
             "change_reason, created_at) VALUES (?, ?, 1, 'Prefers tables', '{}', NULL, 'created', ?)",
             (revision, present, NOW)),
            ("INSERT INTO memory_entries (id, owner_id, kind, scope_kind, scope_id, status, current_revision_id, "
             "normalized_hash, dedup_key, version, sensitivity, use_policy, confirmation_kind, confirmed_at, "
             "created_at, updated_at) VALUES (?, 'local', 'preference', 'global', NULL, 'active', ?, ?, ?, 1, "
             "'normal', 'local_only', 'user_form', ?, ?, ?)",
             (present, revision, _digest(info["key"], "Prefers tables"),
              _global_dedup(info["key"], "  prefers   TABLES "), NOW, NOW, NOW)),       # the same key, normalised
        ]
    db, _ = await _upgraded_with(tmp_path, extra)
    assert _rows(db, "SELECT scope_kind, status, superseded_by, dedup_key FROM memory_entries WHERE id = ?", (P1,)) == [
        ("global", "superseded", present, None)]
    assert _rows(db, "SELECT count(*) FROM memory_proposals WHERE target_entry_id = ? AND status = 'pending'",
                 (P1,)) == [(0,)]
    assert _rows(db, "SELECT status FROM memory_entries WHERE id = ?", (present,)) == [("active",)]
    report = json.loads(_rows(db, "SELECT summary FROM memory_migration_reports WHERE source_version='0103'")[0][0])
    assert (report["already_present"], report["entries_proposed"]) == (1, 5)


async def test_accepting_a_moved_entry_whose_words_a_later_global_entry_took_is_a_known_refusal(upgraded, monkeypatch):
    """A global entry given the same words after 0103: the accept is a 409 with a code, never an IntegrityError."""
    from server import auth
    from server.api.companion import router
    db, _ = upgraded
    async with repository() as repo:
        made = await repo.create(MemoryWrite(content="Prefers chess", scope=MemoryScope(kind="global")), USER)
        await repo.revise(made["id"], made["version"],
                          MemoryWrite(content="Prefers tables", scope=MemoryScope(kind="global")), USER)
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-0103-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    pid = dict(_rows(db, "SELECT target_entry_id, id FROM memory_proposals WHERE status='pending'"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer synthetic-0103-token"}) as api:
        refused = await api.post(f"/api/v1/memory/proposals/{pid[P1]}/resolve", json={"accept": True})
    assert (refused.status_code, refused.json()["detail"]) == (409, {"code": "memory_already_stored"})
    assert _rows(db, "SELECT status, dedup_key FROM memory_entries WHERE id = ?", (P1,)) == [("proposed", None)]
    assert _rows(db, "SELECT status FROM memory_proposals WHERE id = ?", (pid[P1],)) == [("pending",)]


async def test_a_converted_skill_is_one_arslan_can_see_and_read(upgraded):
    """Moved from test_one_arslan_0144 (expert_conversion is gone): the skill is in the index and readable."""
    from server.orchestrator import arslan
    from server.registry.executors import ReadSkillExecutor
    db, _ = upgraded
    assert "expert-2-research-analyst" not in await arslan._skill_index()     # every converted skill starts off
    assert not (await ReadSkillExecutor().execute({"key": "expert-2-research-analyst"}))["ok"]
    _write(db, [("UPDATE skill_packs SET enabled = 1 WHERE key = 'expert-2-research-analyst'", ())])   # the user's yes
    index = await arslan._skill_index()
    assert "expert-2-research-analyst" in index and "expert-5-deploy-helper" not in index
    read = await ReadSkillExecutor().execute({"key": "expert-2-research-analyst"})
    assert read["ok"] and "local speech models" in read["body"]


async def test_private_knowledge_moves_to_one_unbound_collection(upgraded):
    db, _ = upgraded
    [(cid, name, description)] = _rows(db, "SELECT id, name, description FROM collections WHERE id != 9")
    assert (name, description) == (m0103.COLLECTION_NAME, m0103.COLLECTION_DESCRIPTION)
    assert _rows(db, "SELECT spawn_id, collection_id, origin_label, embedding FROM knowledge_chunks WHERE id=41") == [
        (None, cid, "Research Analyst", b"\x00\x00\x80?")]
    assert _rows(db, "SELECT rowid FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH 'speech'") == [(41,)]
    assert all(cid not in json.loads(ids or "[]") for (ids,) in _rows(db, "SELECT collection_ids FROM projects"))


async def test_relayed_answers_become_arslan_replies_with_the_prefix_in_context_only(upgraded):
    db, _ = upgraded
    assert _rows(db, "SELECT id, role, content, display_content, spawn_id FROM arslan_messages ORDER BY id") == [
        (21, "arslan", m0103.RELAYED_PREFIX + "[Mermer] I am Mermer", "[Mermer] I am Mermer", None),
        (22, "arslan", m0103.RELAYED_PREFIX + "context copy", "What the user saw", None)]
    # The FTS index follows the content (0059's update trigger).
    assert _rows(db, "SELECT rowid FROM arslan_messages_fts WHERE arslan_messages_fts MATCH '\"relayed output\"' "
                     "ORDER BY rowid") == [(21,), (22,)]


async def test_the_answer_prompt_reads_a_converted_row_as_a_relayed_one(upgraded):
    """Moved from test_answer_identity (the read-time branch is gone): the attribution is in the data now."""
    from server.orchestrator import memory
    history = (await memory.assemble_working_context("c1"))["history"]
    assert history[0] == {"role": "assistant", "content": "(relayed output from a former expert) [Mermer] I am Mermer"}


async def test_an_expert_task_ends_as_a_cancel_would_end_it(upgraded):
    db, _ = upgraded
    assert _rows(db, "SELECT phase, cancel_requested, pause_reason, version, sequence FROM companion_tasks") == [
        ("cancelled", 1, "task_invalid_driver", 4, 5)]
    assert _rows(db, "SELECT sequence, attempt_id, kind, payload FROM task_events WHERE task_id='task-x'") == [
        (5, "att-x", "cancel_requested", json.dumps({"phase": "cancelled", "spec_revision": 1}))]
    assert _rows(db, "SELECT status FROM task_attempts WHERE id='att-x'") == [("cancelled",)]


async def test_expert_memory_moves_to_global_with_ids_kept_and_waits_for_the_user(upgraded):
    db, _ = upgraded
    assert _rows(db, "SELECT count(*) FROM memory_entries WHERE scope_kind='expert'") == [(0,)]
    entries = {row[0]: row[1:] for row in _rows(
        db, "SELECT id, scope_kind, scope_id, status, version, confirmation_kind, dedup_key FROM memory_entries")}
    assert set(entries) == {P1, P2, A1, Z1, S_OLD, S_NEW, D1, R1, ST1}                  # every id kept
    expected = {P1: "proposed", P2: "proposed", A1: "proposed", Z1: "proposed", S_NEW: "proposed",
                S_OLD: "superseded", R1: "quarantined", ST1: "proposed", D1: "deleted"}
    for entry_id, status in expected.items():
        scope_kind, scope_id, now, version, confirmation, dedup = entries[entry_id]
        assert (scope_kind, scope_id, now) == ("global", None, status), entry_id
        assert version == (1 if entry_id == D1 else 2) and confirmation is None, entry_id
        assert dedup == (None if entry_id != D1 else "dedup-" + D1), entry_id
    pending = {target: (version, candidate, provenance) for target, version, candidate, provenance in _rows(
        db, "SELECT target_entry_id, target_version, candidate, provenance FROM memory_proposals "
            "WHERE status='pending'")}
    assert pending == {e: (2, None, json.dumps({"source_kind": "migration"})) for e in (P1, P2, A1, Z1, S_NEW, ST1)}
    assert _rows(db, "SELECT status, candidate, reason FROM memory_proposals WHERE target_entry_id=? "
                     "AND status != 'pending'", (ST1,)) == [("dismissed", None, m0103.REASON)]
    assert _rows(db, "SELECT status FROM memory_proposals WHERE table_name='spawns'") == [("dismissed",)]
    sources = _rows(db, "SELECT entry_id, source_kind, source_ref, author FROM memory_sources "
                        "WHERE source_kind='migration' ORDER BY entry_id")
    assert [row[0] for row in sources] == sorted({P1, P2, A1, Z1, S_OLD, S_NEW, R1, ST1})
    assert {json.loads(row[2])["from_scope"] for row in sources} == {"expert"} and {row[3] for row in sources} == {"system"}
    assert _rows(db, "SELECT content FROM memory_revisions WHERE entry_id=? AND version=2", (A1,)) == [
        ("Prefers short answers",)]
    assert _rows(db, "SELECT superseded_by FROM memory_entries WHERE id=?", (S_OLD,)) == [(S_NEW,)]


async def test_the_ledger_is_left_as_it_was_and_the_report_holds_counts_only(upgraded):
    db, _ = upgraded
    assert _rows(db, "SELECT deletion_epoch FROM memory_store_state") == [(1,)]
    assert _rows(db, "SELECT entry_id, scope_kind, scope_key FROM memory_deletions") == [(D1, "expert", "2")]
    assert "expert" in manifest._SCOPES
    [(summary,)] = _rows(db, "SELECT summary FROM memory_migration_reports WHERE source_version='0103'")
    report = json.loads(summary)
    assert all(isinstance(value, int) for value in report.values())
    assert report == {"chat_messages_dropped": 1, "chunks_moved": 1, "entries_deleted": 1, "entries_moved": 9,
                      "entries_proposed": 6, "entries_restricted": 1, "entries_superseded": 1, "feedback_dropped": 1,
                      "messages_converted": 2, "proposals_dismissed": 1, "skills_already": 1,
                      "skills_held_off_credential": 1, "skills_made": 4, "skills_too_short": 1, "tasks_ended": 1, "v1_proposals_dismissed": 1}


async def test_the_tables_drop_and_nothing_dangles(upgraded):
    db, _ = upgraded
    tables = _tables(db)
    assert tables & (DROPPED - {"spawns"}) == set()
    assert "distilled_sessions" in tables
    assert _rows(db, "PRAGMA table_info(spawns)") == [(0, "id", "INTEGER", 0, None, 1)]       # the stub, empty
    assert _rows(db, "SELECT count(*) FROM spawns") == [(0,)]
    assert _rows(db, "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='spawns'") == []
    assert _rows(db, "PRAGMA foreign_key_check") == []
    assert _rows(db, "PRAGMA integrity_check") == [("ok",)]


# -- 2. restricted rows and the ledger ------------------------------------------------------------------------------

async def test_moved_entries_can_be_deleted_after_the_drop_one_from_spawns_too(upgraded):
    db, _ = upgraded
    async with repository() as repo:
        restricted = await repo.delete_entry(R1, 2, USER)
        from_spawns = await repo.delete_entry(P2, 2, USER)            # map row source_table='spawns'
    assert restricted["status"] == from_spawns["status"] == "deleted"
    assert _rows(db, "SELECT deletion_epoch FROM memory_store_state") == [(3,)]
    assert ("global", "") in set(_rows(db, "SELECT scope_kind, scope_key FROM memory_deletions WHERE entry_id=?", (P2,)))


async def test_a_restored_store_reconciles_a_manifest_naming_a_moved_entry(upgraded):
    from server.services.memory_restore import mark_restored_sync
    db, info = upgraded
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            value = json.loads(manifest.export_sync(conn))
            value["deletions"].append({"entry_id": P2, "epoch": 1, "content_digest": _digest(info["key"], "x"),
                                       "scope_kind": "expert", "scope_key": "2"})        # an old expert tombstone
            payload = json.dumps(value).encode()
            assert manifest.decode(payload)["deletions"][0]["scope_kind"] == "expert"   # an old manifest validates
            mark_restored_sync(conn)
            assert manifest.reconcile_staged_sync(conn, payload)["deleted_entries"] == 1  # matched by its id
    finally:
        engine.dispose()
    assert _rows(db, "SELECT status FROM memory_entries WHERE id=?", (P2,)) == [("deleted",)]


# -- 3. never auto-accepted -----------------------------------------------------------------------------------------

async def test_moved_entries_wait_one_by_one(upgraded, monkeypatch):
    from server import auth
    from server.api.companion import router
    db, info = upgraded
    async with repository() as repo:
        with pytest.raises(MemoryError, match="memory_confirmation_required"):
            await repo.set_status(A1, 2, "active", USER)           # its confirmation went with the scope
    # Text the user once deleted in global scope (a global tombstone of Z1's words) is refused when accepted.
    _write(db, [("INSERT INTO memory_deletions (id, instance_id, entry_id, epoch, content_digest, scope_kind, "
                 "scope_key, created_at) SELECT '00000000-0000-4000-8000-0000000000d2', instance_id, "
                 "'00000000-0000-4000-8000-0000000000e2', 1, ?, 'global', '', ? FROM memory_store_state",
                 (_digest(info["key"], "Prefers bullet lists"), NOW))])
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-0103-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    pid = dict(_rows(db, "SELECT target_entry_id, id FROM memory_proposals WHERE status='pending'"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer synthetic-0103-token"}) as api:
        assert (await api.get("/api/v1/memory/noticed-earlier")).json() == {"count": 0}
        assert (await api.post("/api/v1/memory/noticed-earlier/accept")).json() == {"accepted": 0}
        listed = {row["target_id"] for row in (await api.get("/api/v1/memory/proposals")).json()}
        assert {P1, P2, A1, Z1, S_NEW, ST1} <= listed
        refused = await api.post(f"/api/v1/memory/proposals/{pid[Z1]}/resolve", json={"accept": True})
        assert refused.json()["detail"] == {"code": "memory_previously_deleted"}
        accepted = await api.post(f"/api/v1/memory/proposals/{pid[P1]}/resolve", json={"accept": True})
        assert accepted.status_code == 200 and accepted.json()["status"] == "active"
        dismissed = await api.post(f"/api/v1/memory/proposals/{pid[ST1]}/resolve", json={"accept": False})
        assert dismissed.status_code == 200
    assert _rows(db, "SELECT status, scope_kind FROM memory_entries WHERE id IN (?, ?) ORDER BY id", (P1, ST1)) == [
        ("active", "global"), ("paused", "global")]


# -- 4. a new install -----------------------------------------------------------------------------------------------

async def test_a_new_install_gets_only_the_triggers(tmp_path):
    db = tmp_path / "arslan.db"
    await _boot(db)
    tables = _tables(db)
    assert tables & DROPPED == set()                                 # no stub either
    assert "origin_label" in {row[1] for row in _rows(db, "PRAGMA table_info(knowledge_chunks)")}
    assert {name for (name,) in _rows(db, "SELECT name FROM sqlite_master WHERE type='trigger' "
                                          "AND tbl_name='memory_entries'")} >= set(pre_0103.RETIRED_TRIGGERS)
    assert _rows(db, "SELECT count(*) FROM memory_migration_reports WHERE source_version='0103'") == [(0,)]
    assert _rows(db, "SELECT count(*) FROM collections") == [(0,)]
    sql = _rows(db, "SELECT sql FROM sqlite_master WHERE name='memory_entries'")[0][0]
    assert pre_0103.NEW_SCOPE_CHECK in sql                             # the narrower CHECK from the model
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with pytest.raises(sa.exc.DBAPIError, match="memory_scope_retired|CHECK constraint"), engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO memory_entries (id, owner_id, kind, scope_kind, scope_id, status, current_revision_id, "
                "version, sensitivity, use_policy, created_at, updated_at) VALUES ('e', 'local', 'preference', "
                "'expert', '3', 'proposed', 'r', 1, 'normal', 'local_only', ?, ?)", (NOW, NOW))
    finally:
        engine.dispose()


async def test_the_triggers_refuse_the_expert_scope_where_the_old_check_still_allows_it(upgraded):
    db, _ = upgraded
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        assert pre_0103.OLD_SCOPE_CHECK in _rows(db, "SELECT sql FROM sqlite_master WHERE name='memory_entries'")[0][0]
        for statement in (
                "UPDATE memory_entries SET scope_kind='expert', scope_id='2' WHERE id='" + P1 + "'",
                "INSERT INTO memory_entries (id, owner_id, kind, scope_kind, scope_id, status, current_revision_id, "
                "version, sensitivity, use_policy, created_at, updated_at) VALUES ('e', 'local', 'preference', "
                "'expert', '3', 'proposed', 'r', 1, 'normal', 'local_only', '', '')"):
            with pytest.raises(sa.exc.DBAPIError, match="memory_scope_retired"), engine.begin() as conn:
                conn.exec_driver_sql(statement)
    finally:
        engine.dispose()


# -- 5. a second run ------------------------------------------------------------------------------------------------

async def test_a_second_run_changes_nothing(upgraded):
    db, _ = upgraded
    dump = "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
    counted = ("skill_packs", "collections", "knowledge_chunks", "memory_entries", "memory_revisions",
               "memory_sources", "memory_proposals", "memory_migration_reports", "task_events", "arslan_messages")
    before = (_rows(db, dump), [_rows(db, f"SELECT * FROM {t} ORDER BY 1") for t in counted])
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            m0103.upgrade_sync(conn)
    finally:
        engine.dispose()
    await _boot(db)
    assert (_rows(db, dump), [_rows(db, f"SELECT * FROM {t} ORDER BY 1") for t in counted]) == before


# -- 6. the stub ----------------------------------------------------------------------------------------------------

async def test_the_tables_that_named_spawns_still_take_writes_and_kept_their_children(upgraded):
    from tests.server.test_c7c5b_no_expert_models import _write_one_of_each
    db, _ = upgraded
    for table in pre_0103.CHILD_TABLES:
        assert "REFERENCES spawns" in _rows(db, "SELECT sql FROM sqlite_master WHERE name=?", (table,))[0][0]
    await _write_one_of_each(db)
    assert _rows(db, "SELECT count(*) FROM run_steps WHERE run_id=11") == [(1,)]
    assert _rows(db, "SELECT count(*) FROM run_evaluations WHERE run_id=11") == [(1,)]
    assert _rows(db, "SELECT count(*) FROM scheduled_task_runs WHERE task_id=12") == [(1,)]
    assert _rows(db, "SELECT spawn_id, spawn_name FROM runs WHERE id=11") == [(None, "Research Analyst")]
    assert _rows(db, "SELECT spawn_id, target FROM scheduled_tasks WHERE id=12") == [(None, "spawn")]
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.exec_driver_sql("UPDATE runs SET spawn_id = 2 WHERE id = 11")     # nothing can point at an expert
    finally:
        engine.dispose()
    assert _rows(db, "PRAGMA foreign_key_check") == []


# -- 7. the guards --------------------------------------------------------------------------------------------------

async def test_guard_a_set_status_refuses_an_expert_row_written_around_the_trigger(upgraded):
    db, _ = upgraded
    _write(db, [("DROP TRIGGER memory_entries_scope_retired_upd", ()),
                ("UPDATE memory_entries SET scope_kind='expert', scope_id='2', confirmation_kind='explicit_user_request', "
                 "confirmed_at=? WHERE id=?", (NOW, A1))])
    async with repository() as repo:
        with pytest.raises(MemoryError, match="memory_scope_retired"):
            await repo.set_status(A1, 2, "active", USER)
        with pytest.raises(MemoryError, match="memory_scope_retired"):
            await repo.set_status(A1, 2, "paused", USER)


async def test_guard_c_merge_into_never_folds_a_write_into_another_scope(upgraded):
    db, _ = upgraded
    before = _rows(db, "SELECT count(*) FROM memory_sources WHERE entry_id=?", (P1,))
    write = MemoryWrite(content="Prefers tables", scope=MemoryScope(kind="domain", id="d1"))
    async with repository() as repo:
        assert await repo.merge_into(P1, 2, write, MemoryActor(origin="host", domain_id="d1")) is None
    assert _rows(db, "SELECT count(*) FROM memory_sources WHERE entry_id=?", (P1,)) == before


@pytest.mark.parametrize("with_spawns", [True, False], ids=["spawns-left", "spawns-gone"])
async def test_guard_b_an_unactivated_install_maps_expert_memory_to_global_quarantined(tmp_path, with_spawns):
    """An install whose memory v2 never activated. With `spawns` still there, 0103's step 0 maps the experts'
    preferences before the table goes; with only the stub left, activation runs after 0103 (whose trigger
    refuses the expert scope). Either way the expert learning, and the preference, land in global, quarantined, with no proposal."""
    from server.db import models
    db = tmp_path / "arslan.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            runner.prepare_upgrade_backup(conn)
            models.Base.metadata.create_all(conn)
            runner.apply_pending(conn)
    finally:
        engine.dispose()
    pre_0103.restore_child_tables(db)
    expert = ([*[(s, ()) for s in pre_0103.statements("tables")],
               _spawn(3, "Synthetic expert", LONG, facts=["Prefers short answers"])] if with_spawns
              else [("CREATE TABLE spawns (id INTEGER PRIMARY KEY)", ())])        # what an earlier 0103 left
    _write(db, [("PRAGMA foreign_keys=OFF", ()), *expert,
                ("INSERT INTO learnings (id, content, source_kind, source_ref, spawn_id) "
                 "VALUES (5, 'Check units first', 'distill', '{}', 3)", ())])
    assert _rows(db, "SELECT phase FROM memory_store_state") != [("active",)]
    await _boot(db)
    rows = _rows(db, "SELECT m.source_table, e.scope_kind, e.scope_id, e.status FROM memory_legacy_map m "
                     "JOIN memory_entries e ON e.id = m.entry_id ORDER BY m.source_table")
    assert rows == [("learnings", "global", None, "quarantined")] + (
        [("spawns", "global", None, "quarantined")] if with_spawns else [])
    assert _rows(db, "SELECT count(*) FROM memory_proposals") == [(0,)]
    refs = [json.loads(ref) for (ref,) in _rows(db, "SELECT source_ref FROM memory_sources WHERE source_kind='legacy'")]
    assert sorted(ref.get("spawn_id") for ref in refs) == [3] * len(rows)
    assert _rows(db, "SELECT phase FROM memory_store_state") == [("active",)]
