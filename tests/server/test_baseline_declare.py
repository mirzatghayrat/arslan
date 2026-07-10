"""S2 E9 — clean-corpus baseline declaration + boot canary.

The developer manually declares `evolution_baseline_started_at` (spec §E9 / audit #12) so
runs created DURING S2 dev/testing (which are epoch=1 too, since E1..E8 all landed on this
branch) never pollute the real corpus. build_corpus/replay_set additionally filter real runs
to `created_at >= baseline_started_at`. A boot canary counts epoch=0 live runs created AFTER
the baseline — a missed recorder path that would starve the corpus.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from server.db.models import Run, Spawn
from server.services import replay_gate, replay_run, replay_set, settings_service

_BASE = datetime(2026, 7, 11, 12, 0, 0)
_BEFORE = _BASE - timedelta(hours=1)
_AFTER = _BASE + timedelta(hours=1)


async def _seed_spawn(client, name="S") -> int:
    async with client.db_maker() as db:
        s = Spawn(name=name, domain_category="x", system_prompt="P",
                  generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


# ── 1. settings round-trip ────────────────────────────────────────────────────────────

async def test_baseline_setting_roundtrip(client):
    async with client.db_maker() as db:
        assert await settings_service.get_baseline_started_at(db) is None
        await settings_service.set_baseline_started_at(db, _BASE)
    async with client.db_maker() as db:
        got = await settings_service.get_baseline_started_at(db)
    assert got == _BASE


# ── 2. declare + GET endpoints ────────────────────────────────────────────────────────

async def test_declare_endpoint_sets_baseline(client):
    r0 = await client.get("/api/v1/evolution/baseline")
    assert r0.status_code == 200
    assert r0.json()["baseline_started_at"] is None
    assert r0.json()["epoch1_runs_after"] == 0

    r1 = await client.post("/api/v1/evolution/baseline/declare")
    assert r1.status_code == 200
    declared = r1.json()["baseline_started_at"]
    assert declared  # a non-empty ISO string

    r2 = await client.get("/api/v1/evolution/baseline")
    assert r2.status_code == 200
    assert r2.json()["baseline_started_at"] == declared


async def test_baseline_get_counts_epoch1_after(client):
    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        await settings_service.set_baseline_started_at(db, _BASE)
        # two live epoch=1 AFTER baseline → counted
        db.add(Run(conversation_id="c", spawn_id=sid, user_message="a", status="scored",
                   kind="live", epoch=1, created_at=_AFTER))
        db.add(Run(conversation_id="c", spawn_id=sid, user_message="b", status="scored",
                   kind="live", epoch=1, created_at=_AFTER))
        # one live epoch=1 BEFORE baseline → NOT counted (dev-era pollution)
        db.add(Run(conversation_id="c", spawn_id=sid, user_message="c", status="scored",
                   kind="live", epoch=1, created_at=_BEFORE))
        # a replay arm after baseline → NOT counted
        db.add(Run(conversation_id="c", spawn_id=sid, user_message="d", status="replayed",
                   kind="replay", epoch=1, created_at=_AFTER))
        await db.commit()

    r = await client.get("/api/v1/evolution/baseline")
    assert r.status_code == 200
    assert r.json()["epoch1_runs_after"] == 2


# ── 3. build_corpus created_at filter ─────────────────────────────────────────────────

async def _mk_run(db, sid, msg, created_at):
    r = Run(conversation_id="c", spawn_id=sid, user_message=msg, status="scored",
            kind="live", epoch=1, created_at=created_at)
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r.id


async def test_build_corpus_filters_by_baseline(client, monkeypatch):
    async def _always_replayable(db, run_id):
        return True
    monkeypatch.setattr(replay_run, "is_replayable", _always_replayable)

    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        await settings_service.set_baseline_started_at(db, _BASE)
        before_id = await _mk_run(db, sid, "before", _BEFORE)
        after_id = await _mk_run(db, sid, "after", _AFTER)

    async with client.db_maker() as db:
        # baseline read from settings (param defaults to None → read-from-settings)
        corpus = await replay_gate.build_corpus(db, sid)
    real = [c for c in corpus if c["corpus_label"] == "real"]
    assert len(real) == 1
    assert real[0]["source_ref"] == after_id
    assert before_id not in [c["source_ref"] for c in real]


async def test_build_corpus_no_baseline_backcompat(client, monkeypatch):
    """No baseline declared → every epoch=1 live scored run is a candidate (back-compat)."""
    async def _always_replayable(db, run_id):
        return True
    monkeypatch.setattr(replay_run, "is_replayable", _always_replayable)

    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        await _mk_run(db, sid, "before", _BEFORE)
        await _mk_run(db, sid, "after", _AFTER)

    async with client.db_maker() as db:
        corpus = await replay_gate.build_corpus(db, sid)
    real = [c for c in corpus if c["corpus_label"] == "real"]
    assert len(real) == 2


async def test_build_corpus_explicit_since_overrides_settings(client, monkeypatch):
    """An explicit baseline_started_at (the living-proposal `since`) overrides the setting."""
    async def _always_replayable(db, run_id):
        return True
    monkeypatch.setattr(replay_run, "is_replayable", _always_replayable)

    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        await settings_service.set_baseline_started_at(db, _BEFORE)  # setting = permissive
        await _mk_run(db, sid, "before", _BEFORE)
        after_id = await _mk_run(db, sid, "after", _AFTER)

    async with client.db_maker() as db:
        corpus = await replay_gate.build_corpus(db, sid, baseline_started_at=_BASE)
    real = [c for c in corpus if c["corpus_label"] == "real"]
    assert len(real) == 1
    assert real[0]["source_ref"] == after_id


# ── 4. replay_set filter ──────────────────────────────────────────────────────────────

async def test_replay_set_build_filters_by_baseline(client, monkeypatch):
    sid = await _seed_spawn(client)
    from server.db.models import ArslanMessage
    async with client.db_maker() as db:
        await settings_service.set_baseline_started_at(db, _BASE)
        before_id = await _mk_run(db, sid, "before", _BEFORE)
        after_id = await _mk_run(db, sid, "after", _AFTER)
        for rid in (before_id, after_id):
            db.add(ArslanMessage(conversation_id="c", run_id=rid, role="spawn_summary",
                                 content="out"))
        await db.commit()

    # replay_set.build opens its OWN AsyncSessionLocal; point it at the test DB.
    from server.db import session as db_session
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    items = await replay_set.build(sid)
    assert [it["run_id"] for it in items] == [after_id]


# ── 5. boot canary helper ─────────────────────────────────────────────────────────────

async def test_canary_counts_epoch0_after_baseline(client):
    sid = await _seed_spawn(client)
    async with client.db_maker() as db:
        # no baseline set yet → 0
        assert await replay_gate.count_epoch0_after_baseline(db) == 0
        await settings_service.set_baseline_started_at(db, _BASE)
        # missed recorder path: live epoch=0 AFTER baseline → counted
        db.add(Run(conversation_id="c", spawn_id=sid, user_message="miss", status="scored",
                   kind="live", epoch=0, created_at=_AFTER))
        # epoch=0 BEFORE baseline (pre-baseline, expected) → NOT counted
        db.add(Run(conversation_id="c", spawn_id=sid, user_message="old", status="scored",
                   kind="live", epoch=0, created_at=_BEFORE))
        # epoch=1 after → NOT counted (correct path)
        db.add(Run(conversation_id="c", spawn_id=sid, user_message="ok", status="scored",
                   kind="live", epoch=1, created_at=_AFTER))
        # replay epoch=0 after → NOT counted (never enters corpus anyway)
        db.add(Run(conversation_id="c", spawn_id=sid, user_message="rep", status="replayed",
                   kind="replay", epoch=0, created_at=_AFTER))
        await db.commit()

    async with client.db_maker() as db:
        assert await replay_gate.count_epoch0_after_baseline(db) == 1
