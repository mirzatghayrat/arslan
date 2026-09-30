"""0.1.47 service: what gets stored, what interrupts, and that every way out of an
item (accept / snooze / dismiss) leaves the data in a state the next scan agrees with."""
import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from arslan.proactive_policy import Candidate, Evidence, ProactiveConfig
from server.db.models import ProactiveItem, ProactiveMute, ProactiveSpend, ProactiveWatch, ScheduledTask, Setting
from server.services import background_jobs, desktop_status, proactive_detectors as det, proactive_service as svc
from server.services.proactive_service import ProactiveError

NOON = datetime(2026, 9, 30, 12, 0, 0)        # local == UTC in these tests; outside quiet hours


def cand(n=1, *, kind="web_change", goal="Look at what changed", evidence=None, **over):
    base = dict(kind=kind, fingerprint=f"fp:{n}", source_key=f"watch:{n}", title_key=f"title.{kind}",
                evidence=tuple(evidence if evidence is not None else [Evidence("web.changed", {"n": 2})]), goal=goal)
    base.update(over)
    return Candidate(**base)


def found(*candidates, ack=None):
    return [det.Found(c, ack) for c in candidates]


async def ingest(items, config=None, now=NOON):
    return await svc.ingest(items, now_utc=now, now_local=now, config=config or ProactiveConfig())


async def rows(execution_db):
    async with execution_db() as db:
        return (await db.execute(select(ProactiveItem).order_by(ProactiveItem.id))).scalars().all()


@pytest.fixture(autouse=True)
def events(monkeypatch):
    """Desktop notifications this test raised (the real queue is process-global)."""
    seen = []
    monkeypatch.setattr(desktop_status, "push", lambda kind, **kw: seen.append((kind, kw)))
    return seen


# ── config ───────────────────────────────────────────────────────────────────

async def test_config_defaults_spend_nothing(execution_db):
    config = await svc.load_config()
    assert config.enabled and config.diagnosis_daily_usd == 0 and not config.brief_enabled


async def test_config_patch_merges_and_persists(execution_db):
    await svc.save_config({"notify_daily_cap": 2})
    saved = await svc.save_config({"brief_enabled": True})
    assert (saved.notify_daily_cap, saved.brief_enabled) == (2, True)
    assert (await svc.load_config()).notify_daily_cap == 2


@pytest.mark.parametrize("patch", [{"quiet_start": "25:00"}, {"diagnosis_daily_usd": 50}, {"surprise": 1}])
async def test_a_bad_config_patch_is_refused_and_changes_nothing(execution_db, patch):
    with pytest.raises(ProactiveError) as err:
        await svc.save_config(patch)
    assert err.value.code == "invalid_config"
    assert await svc.load_config() == ProactiveConfig()


async def test_unreadable_stored_config_falls_back_to_the_free_defaults(execution_db):
    async with execution_db() as db:
        db.add(Setting(key=svc.CONFIG_KEY, value="{not json"))
        await db.commit()
    assert await svc.load_config() == ProactiveConfig()


# ── ingest ───────────────────────────────────────────────────────────────────

async def test_a_passing_candidate_becomes_an_item_with_its_evidence(execution_db):
    result = await ingest(found(cand(1, evidence=[Evidence("web.changed", {"n": 2}, quote="Price: 9")])))
    [item] = await rows(execution_db)
    assert result["created"] == [item.id] and item.status == "new"
    assert item.evidence == [{"key": "web.changed", "params": {"n": 2}, "quote": "Price: 9"}]
    assert item.created_at == NOON and item.goal == "Look at what changed"


async def test_the_same_evidence_twice_is_one_item(execution_db):
    await ingest(found(cand(1)))
    again = await ingest(found(cand(1)))
    assert again["created"] == [] and again["rejected"] == {"duplicate": 1}
    assert len(await rows(execution_db)) == 1


async def test_rejections_are_counted_by_reason_not_swallowed(execution_db):
    result = await ingest(found(cand(1, evidence=[]), cand(2, goal=""), cand(3)))
    assert result["rejected"] == {"no_evidence": 1, "no_goal": 1} and len(result["created"]) == 1


async def test_a_muted_source_and_a_muted_kind_are_both_honoured(execution_db):
    async with execution_db() as db:
        db.add_all([ProactiveMute(key="watch:1", created_at=NOON), ProactiveMute(key="kind:folder_change", created_at=NOON)])
        await db.commit()
    result = await ingest(found(cand(1), cand(2, kind="folder_change"), cand(3)))
    assert result["rejected"] == {"muted_source": 1, "muted_kind": 1} and len(result["created"]) == 1


async def test_a_watch_baseline_moves_only_after_the_item_is_stored(execution_db):
    """The ack is what tells a detector 'you may forget the old page'. If it ran
    first, a crash between the two would lose the change for good."""
    at_ack = []

    async def ack():
        at_ack.append([i.fingerprint for i in await rows(execution_db)])

    await ingest(found(cand(1), ack=ack))
    assert at_ack == [["fp:1"]]


async def test_a_failing_ack_does_not_hide_the_stored_item_from_the_caller(execution_db):
    async def boom():
        raise RuntimeError("db went away")

    with pytest.raises(RuntimeError):
        await ingest(found(cand(1), ack=boom))
    assert len(await rows(execution_db)) == 1          # stored; the next scan sees a duplicate, not a loss


# ── notifications ────────────────────────────────────────────────────────────

async def test_a_notifying_kind_raises_one_quiet_notification(execution_db, events):
    result = await ingest(found(cand(1)))
    [item] = await rows(execution_db)
    assert result["notified"] == 1 and item.notified_at == NOON
    assert events == [("proactive", {"outcome": "ok"})]


async def test_quiet_hours_store_the_item_but_stay_silent(execution_db, events):
    night = datetime(2026, 9, 30, 23, 30)
    result = await ingest(found(cand(1)), now=night)
    [item] = await rows(execution_db)
    assert len(result["created"]) == 1 and item.notified_at is None and events == []


async def test_the_daily_cap_counts_today_only(execution_db, events):
    config = ProactiveConfig(notify_daily_cap=2)
    await ingest(found(cand(1), cand(2), cand(3)), config)
    assert len(events) == 2
    tomorrow = NOON + timedelta(days=1)
    await ingest(found(cand(4)), config, now=tomorrow)
    assert len(events) == 3


async def test_job_followups_never_interrupt(execution_db, events):
    await ingest(found(cand(1, kind="job_followup")))
    assert events == [] and len(await rows(execution_db)) == 1


async def test_notify_off_keeps_the_inbox_but_not_the_pop_up(execution_db, events):
    await ingest(found(cand(1)), ProactiveConfig(notify=False))
    assert events == [] and len(await rows(execution_db)) == 1


# ── the brief ────────────────────────────────────────────────────────────────

async def test_no_brief_when_there_is_nothing_to_say(execution_db):
    assert await svc.build_brief(NOON, NOON, "en") is None


async def test_the_brief_counts_what_is_open_running_and_due_soon(execution_db, monkeypatch):
    await ingest(found(cand(1), cand(2, kind="job_followup")), ProactiveConfig(notify=False))
    async with execution_db() as db:
        db.add(ScheduledTask(name="Weekly numbers", prompt="p", schedule_kind="interval", interval_s=3600, enabled=True,
                             next_due_at=NOON + timedelta(hours=3)))
        db.add(ScheduledTask(name=det.HEARTBEAT_NAME, prompt="p", schedule_kind="interval", interval_s=3600, enabled=True,
                             next_due_at=NOON + timedelta(hours=1)))
        await db.commit()
    monkeypatch.setitem(background_jobs._jobs, "j1", SimpleNamespace(phase="running", goal="Compare two phones"))
    monkeypatch.setitem(background_jobs._jobs, "j2", SimpleNamespace(phase="finished", goal="old"))
    brief = await svc.build_brief(NOON, NOON, "en")
    c = brief.candidate
    assert (c.kind, c.fingerprint, c.goal) == ("brief", "brief:2026-09-30", "")
    keys = {e.key: e for e in c.evidence}
    assert keys["brief.open"].params["count"] == 2
    assert keys["brief.running"].params["count"] == 1 and keys["brief.running"].quote == "Compare two phones"
    assert keys["brief.schedules"].params["count"] == 1 and keys["brief.schedules"].quote == "Weekly numbers"


async def test_one_brief_a_day_and_only_when_switched_on(execution_db):
    await ingest(found(cand(1)), ProactiveConfig(notify=False))
    off = await svc.scan_once(now_utc=NOON, now_local=NOON)
    assert not any(i.kind == "brief" for i in await rows(execution_db)) and off is not None
    await svc.save_config({"brief_enabled": True, "brief_time": "08:30", "watches": False})
    await svc.scan_once(now_utc=NOON, now_local=NOON)
    await svc.scan_once(now_utc=NOON + timedelta(hours=1), now_local=NOON + timedelta(hours=1))
    assert [i.fingerprint for i in await rows(execution_db) if i.kind == "brief"] == ["brief:2026-09-30"]


# ── scanning ─────────────────────────────────────────────────────────────────

async def test_a_disabled_feature_scans_nothing_unless_asked(execution_db, monkeypatch):
    calls = []

    async def detector(ctx):
        calls.append(1)
        return []

    monkeypatch.setitem(det.DETECTORS, "job_followups", detector)
    await svc.save_config({"enabled": False})
    assert await svc.scan_once(now_utc=NOON, now_local=NOON) == {"skipped": "disabled"} and calls == []
    await svc.scan_once(now_utc=NOON, now_local=NOON, manual=True)
    assert calls == [1]


async def test_one_broken_detector_does_not_stop_the_others(execution_db, monkeypatch):
    async def broken(ctx):
        raise RuntimeError("boom")

    async def fine(ctx):
        return found(cand(7))

    monkeypatch.setitem(det.DETECTORS, "job_followups", broken)
    monkeypatch.setitem(det.DETECTORS, "scheduled_problems", fine)
    result = await svc.scan_once(now_utc=NOON, now_local=NOON)
    assert len(result["created"]) == 1


async def test_a_switched_off_source_is_not_even_consulted(execution_db, monkeypatch):
    called = []

    async def spy(ctx):
        called.append(1)
        return []

    monkeypatch.setitem(det.DETECTORS, "web_changes", spy)
    await svc.save_config({"watches": False})
    await svc.scan_once(now_utc=NOON, now_local=NOON)
    assert called == []


# ── accept / snooze / dismiss ────────────────────────────────────────────────

@pytest.fixture
def started(monkeypatch):
    calls = []

    async def start(conversation_id, goal, criteria):
        calls.append((conversation_id, goal, criteria))
        return SimpleNamespace(job_id="job-42")

    monkeypatch.setattr(background_jobs, "start", start)
    return calls


async def one_item(execution_db, **over):
    await ingest(found(cand(1, **over)), ProactiveConfig(notify=False))
    return (await rows(execution_db))[0].id


async def test_accepting_starts_one_job_with_the_items_goal_and_criteria(execution_db, started):
    item_id = await one_item(execution_db, criteria=({"description": "Saved as r.md", "kind": "file_saved", "target": "r.md"},))
    out = await svc.accept(item_id, "conv-1")
    [item] = await rows(execution_db)
    assert out == {"job_id": "job-42", "conversation_id": "conv-1"}
    assert started == [("conv-1", "Look at what changed", [{"description": "Saved as r.md", "kind": "file_saved", "target": "r.md"}])]
    assert (item.status, item.job_id, item.conversation_id) == ("accepted", "job-42", "conv-1") and item.acted_at


async def test_two_clicks_that_both_saw_the_item_open_start_one_job(execution_db, started, monkeypatch):
    """Force the bad interleaving instead of hoping for it: both calls have read
    the item as still open before either has claimed it. Only the conditional
    UPDATE keeps this to one job."""
    item_id = await one_item(execution_db)
    real_get, reads, both_read = svc._get, [], asyncio.Event()

    async def get_after_both_read(db, wanted):
        item = await real_get(db, wanted)
        if len(reads) < 2:
            reads.append(1)
            if len(reads) == 2:
                both_read.set()
            await both_read.wait()
        return item

    monkeypatch.setattr(svc, "_get", get_after_both_read)
    results = await asyncio.gather(svc.accept(item_id, "c"), svc.accept(item_id, "c"), return_exceptions=True)
    assert len(started) == 1
    assert sum(isinstance(r, ProactiveError) and r.code == "already_handled" for r in results) == 1


async def test_if_the_job_cannot_start_the_item_comes_back(execution_db, monkeypatch):
    async def start(*args):
        raise RuntimeError("no provider")

    monkeypatch.setattr(background_jobs, "start", start)
    item_id = await one_item(execution_db)
    with pytest.raises(RuntimeError):
        await svc.accept(item_id, "c")
    [item] = await rows(execution_db)
    assert item.status == "new" and item.acted_at is None and item.job_id is None


@pytest.mark.parametrize("conversation", ["", "x" * 51])
async def test_accept_needs_a_real_conversation(execution_db, started, conversation):
    item_id = await one_item(execution_db)
    with pytest.raises(ProactiveError) as err:
        await svc.accept(item_id, conversation)
    assert err.value.code == "invalid_conversation" and started == []


async def test_a_follow_up_reports_into_the_conversation_it_came_from(execution_db, started):
    item_id = await one_item(execution_db, kind="job_followup", conversation_id="origin-conv")
    assert (await svc.accept(item_id))["conversation_id"] == "origin-conv" and started[0][0] == "origin-conv"


async def test_a_chosen_conversation_wins_over_the_origin(execution_db, started):
    item_id = await one_item(execution_db, kind="job_followup", conversation_id="origin-conv")
    assert (await svc.accept(item_id, "other"))["conversation_id"] == "other"


async def test_with_no_origin_and_no_choice_there_is_nowhere_to_report(execution_db, started):
    item_id = await one_item(execution_db)
    with pytest.raises(ProactiveError) as err:
        await svc.accept(item_id)
    assert err.value.code == "invalid_conversation" and started == []


async def test_a_brief_is_read_not_run(execution_db, started):
    await ingest(found(cand(1, kind="brief", goal="")), ProactiveConfig(notify=False))
    with pytest.raises(ProactiveError) as err:
        await svc.accept((await rows(execution_db))[0].id, "c")
    assert err.value.code == "nothing_to_do" and started == []


async def test_a_handled_item_cannot_be_accepted_again(execution_db, started):
    item_id = await one_item(execution_db)
    await svc.dismiss(item_id)
    with pytest.raises(ProactiveError) as err:
        await svc.accept(item_id, "c")
    assert err.value.code == "already_handled" and started == []


async def test_unknown_item(execution_db):
    for call in (svc.snooze(999, 1), svc.dismiss(999), svc.accept(999, "c")):
        with pytest.raises(ProactiveError) as err:
            await call
        assert err.value.code == "item_not_found"


async def test_snooze_hides_it_and_maintain_wakes_it(execution_db):
    item_id = await one_item(execution_db)
    await svc.snooze(item_id, 3)
    assert await svc.list_items("open") == [] and (await svc.summary())["open"] == 0
    await svc.maintain(datetime.utcnow() + timedelta(days=2))
    assert (await rows(execution_db))[0].status == "snoozed"
    await svc.maintain(datetime.utcnow() + timedelta(days=4))
    [item] = await rows(execution_db)
    assert item.status == "new" and item.snooze_until is None


async def test_only_the_offered_snooze_lengths_are_accepted(execution_db):
    item_id = await one_item(execution_db)
    with pytest.raises(ProactiveError) as err:
        await svc.snooze(item_id, 365)
    assert err.value.code == "invalid_snooze"


async def test_dismiss_can_mute_the_source_and_that_stops_its_watch(execution_db):
    async with execution_db() as db:
        db.add(ProactiveWatch(id=5, kind="web", target="https://example.com/", label="Example", interval_s=3600,
                              enabled=True, created_at=NOON))
        await db.commit()
    await ingest(found(cand(5)), ProactiveConfig(notify=False))
    await svc.dismiss((await rows(execution_db))[0].id, mute="source")
    assert await svc.list_mutes() == ["watch:5"]
    assert (await svc.list_watches())[0]["enabled"] is False
    again = await ingest(found(cand(5, fingerprint="fp:other")))
    assert again["rejected"] == {"muted_source": 1}


async def test_turning_a_watch_back_on_lifts_its_mute(execution_db):
    async with execution_db() as db:
        db.add(ProactiveWatch(id=5, kind="web", target="https://example.com/", label="E", interval_s=3600,
                              enabled=False, created_at=NOON))
        db.add(ProactiveMute(key="watch:5", created_at=NOON))
        await db.commit()
    await svc.update_watch(5, {"enabled": True})
    assert await svc.list_mutes() == []


async def test_dismiss_can_mute_a_whole_kind_and_unmute_undoes_it(execution_db):
    item_id = await one_item(execution_db)
    await svc.dismiss(item_id, mute="kind")
    assert await svc.list_mutes() == ["kind:web_change"]
    await svc.unmute("kind:web_change")
    assert await svc.list_mutes() == []
    with pytest.raises(ProactiveError):
        await svc.dismiss(item_id, mute="everything")


async def test_unread_and_high_counts_follow_the_user_reading(execution_db):
    await ingest(found(cand(1, priority="high"), cand(2)), ProactiveConfig(notify=False))
    assert await svc.summary() == {"open": 2, "unread": 2, "high": 1}
    await svc.mark_seen([i.id for i in await rows(execution_db)])
    assert await svc.summary() == {"open": 2, "unread": 0, "high": 0}


async def test_list_puts_the_urgent_first_and_scopes_done_items_apart(execution_db):
    await ingest(found(cand(1), cand(2, priority="high"), cand(3)), ProactiveConfig(notify=False))
    ids = [i["id"] for i in await svc.list_items("open")]
    assert ids[0] == (await rows(execution_db))[1].id
    await svc.dismiss(ids[0])
    assert [i["id"] for i in await svc.list_items("done")] == [ids[0]] and len(await svc.list_items("open")) == 2


# ── maintenance: everything is bounded ───────────────────────────────────────

async def test_stale_open_items_expire_but_are_kept(execution_db):
    await ingest(found(cand(1, kind="brief", goal="")), ProactiveConfig(notify=False), now=NOON - timedelta(days=3))
    await ingest(found(cand(2)), ProactiveConfig(notify=False), now=NOON - timedelta(days=3))
    await svc.maintain(NOON)
    assert {i.kind: i.status for i in await rows(execution_db)} == {"brief": "expired", "web_change": "new"}


async def test_old_finished_items_are_deleted_open_ones_never(execution_db):
    await ingest(found(cand(1), cand(2)), ProactiveConfig(notify=False), now=NOON - timedelta(days=100))
    async with execution_db() as db:
        first = (await db.execute(select(ProactiveItem).order_by(ProactiveItem.id))).scalars().first()
        first.status = "dismissed"
        await db.commit()
    await svc.prune(NOON)
    assert [i.fingerprint for i in await rows(execution_db)] == ["fp:2"]


async def test_the_row_cap_drops_finished_items_and_keeps_every_open_one(execution_db, monkeypatch):
    monkeypatch.setattr(svc, "MAX_ROWS", 5)
    async with execution_db() as db:
        for n in range(8):
            db.add(ProactiveItem(kind="web_change", fingerprint=f"f{n}", source_key="s", title_key="t",
                                 evidence=[{"key": "k"}], goal="g", status="new" if n < 2 else "dismissed",
                                 created_at=NOON))
        await db.commit()
    await svc.prune(NOON)
    left = await rows(execution_db)
    # The open items are the OLDEST rows, so a cap that ignored status would cut them first.
    assert len(left) == 5 and [i.fingerprint for i in left if i.status == "new"] == ["f0", "f1"]


async def test_old_spend_rows_are_trimmed(execution_db):
    async with execution_db() as db:
        db.add_all([ProactiveSpend(day="2026-01-01", micro_usd=5), ProactiveSpend(day="2026-09-29", micro_usd=7)])
        await db.commit()
    await svc.prune(NOON)
    async with execution_db() as db:
        assert [r.day for r in (await db.execute(select(ProactiveSpend))).scalars()] == ["2026-09-29"]


# ── watches ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["http://example.com/", "https://example.com:8443/", "ftp://x/", "https://u:p@example.com/", ""])
async def test_only_https_pages_can_be_watched(execution_db, url):
    with pytest.raises(ProactiveError) as err:
        await svc.add_watch("web", url)
    assert err.value.code == "invalid_url"


async def test_a_web_watch_gets_a_readable_default_label(execution_db):
    watch = await svc.add_watch("web", "https://example.com/pricing", interval_s=3600)
    assert (watch["label"], watch["interval_s"], watch["enabled"], watch["notify"]) == ("example.com", 3600, True, True)


@pytest.mark.parametrize("interval", [59, 1799, 7 * 86400 + 1, "3600", True, None])
async def test_intervals_are_bounded(execution_db, interval):
    with pytest.raises(ProactiveError) as err:
        await svc.add_watch("web", "https://example.com/", interval_s=interval)
    assert err.value.code == "invalid_interval"


async def test_a_folder_watch_needs_a_workspace_and_stays_inside_it(execution_db, tmp_path):
    inbox = tmp_path / "work" / "inbox"
    inbox.mkdir(parents=True)
    with pytest.raises(ProactiveError) as err:
        await svc.add_watch("folder", str(inbox))
    assert err.value.code == "workspace_required"
    async with execution_db() as db:
        db.add(Setting(key="workspace_dir", value=str(tmp_path / "work")))
        await db.commit()
    assert (await svc.add_watch("folder", str(inbox)))["label"] == "inbox"
    for outside in (str(tmp_path), str(tmp_path / "work" / "missing"), str(tmp_path / "work" / ".." / "x")):
        with pytest.raises(ProactiveError) as err:
            await svc.add_watch("folder", outside)
        assert err.value.code == "outside_workspace"


async def test_unknown_kind_and_the_watch_cap(execution_db, monkeypatch):
    with pytest.raises(ProactiveError) as err:
        await svc.add_watch("rss", "https://example.com/")
    assert err.value.code == "invalid_kind"
    monkeypatch.setattr(svc, "MAX_WATCHES", 2)
    await svc.add_watch("web", "https://a.example/")
    await svc.add_watch("web", "https://b.example/")
    with pytest.raises(ProactiveError) as err:
        await svc.add_watch("web", "https://c.example/")
    assert err.value.code == "too_many_watches"


async def test_update_and_delete_a_watch(execution_db):
    watch = await svc.add_watch("web", "https://example.com/")
    out = await svc.update_watch(watch["id"], {"interval_s": 7200, "notify": False, "label": "  My   page "})
    assert (out["interval_s"], out["notify"], out["label"]) == (7200, False, "My page")
    with pytest.raises(ProactiveError):
        await svc.update_watch(watch["id"], {"interval_s": 5})
    with pytest.raises(ProactiveError) as err:
        await svc.update_watch(999, {})
    assert err.value.code == "watch_not_found"
    await svc.delete_watch(watch["id"])
    assert await svc.list_watches() == []


async def test_what_the_api_returns_is_json_safe(execution_db):
    await ingest(found(cand(1, evidence=[Evidence("web.changed", {"n": 2}, quote="x")])))
    json.dumps(await svc.list_items("open"))
    await svc.add_watch("web", "https://example.com/")
    json.dumps(await svc.list_watches())


# ── the loop ─────────────────────────────────────────────────────────────────

async def test_the_loop_scans_repeatedly_survives_a_failure_and_stops_cleanly(execution_db, monkeypatch):
    runs = []

    async def scan(**kw):
        runs.append(1)
        if len(runs) == 1:
            raise RuntimeError("first scan fails")

    monkeypatch.setattr(svc, "scan_once", scan)
    svc.start(interval=0.01, first_delay=0.01)
    svc.start(interval=0.01, first_delay=0.01)            # a second start is a no-op
    await asyncio.sleep(0.2)
    await svc.stop()
    count = len(runs)
    assert count >= 2
    await asyncio.sleep(0.05)
    assert len(runs) == count and svc._loop_task is None


async def test_stop_before_the_first_scan_never_scans(execution_db, monkeypatch):
    runs = []

    async def scan(**kw):
        runs.append(1)

    monkeypatch.setattr(svc, "scan_once", scan)
    svc.start(interval=10, first_delay=30)
    await svc.stop()
    assert runs == []
