"""0.1.47 detectors: what is worth raising, what is not, and that nothing moves a
watch's baseline until the item has been handled."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from arslan.proactive_policy import ProactiveConfig
from server.db.models import CompanionTask, ProactiveWatch, ScheduledTask, ScheduledTaskRun, TaskRevision
from server.services import proactive_detectors as det

NOW = datetime(2026, 9, 30, 12, 0, 0)


def ctx(**over):
    base = dict(now=NOW, config=ProactiveConfig(), locale="en")
    base.update(over)
    return det.Context(**base)


async def add_task(db, task_id, *, phase="waiting_user", reason="task_budget_exhausted", driver="background",
                   age=timedelta(hours=1), goal="Research local speech models", acceptance=None, conversation="c1"):
    db.add(CompanionTask(id=task_id, owner_id="local", conversation_id=conversation, phase=phase,
                         attempt_id="a", budget={}, privacy={"driver": {"kind": driver}}, pause_reason=reason,
                         updated_at=NOW - age, created_at=NOW - age))
    db.add(TaskRevision(task_id=task_id, revision=1, spec={
        "instruction": goal, "acceptance": acceptance or [
            {"id": "answer-delivered", "description": "d", "evaluator": "deterministic", "rule": {"kind": "text", "minimum": 1}},
            {"id": "criterion-1", "description": "Saved as report.md", "evaluator": "deterministic",
             "rule": {"kind": "artifact", "target": "report.md"}}]}))


# ── jobs that did not finish the job ─────────────────────────────────────────

async def test_a_stopped_job_becomes_a_follow_up_with_its_own_standards(execution_db):
    async with execution_db() as db:
        await add_task(db, "job-1")
        await db.commit()
    [found] = await det.job_followups(ctx())
    c = found.candidate
    assert (c.kind, c.fingerprint, c.source_key, c.conversation_id) == ("job_followup", "job:job-1", "job:job-1", "c1")
    assert c.priority == "high"                                   # it ran out of budget: worth a look
    assert c.evidence[0].quote == "Research local speech models"
    assert c.evidence[1].key == "job.reason.task_budget_exhausted"
    assert "Research local speech models" in c.goal and "already saved" in c.goal
    assert list(c.criteria) == [{"description": "Saved as report.md", "kind": "file_saved", "target": "report.md"}]
    assert found.ack is None


@pytest.mark.parametrize("make", [
    dict(driver="host"),                                          # a chat turn is not a job
    dict(phase="cancelled"),                                      # the user stopped it
    dict(phase="succeeded", reason=None),                         # it finished
    dict(age=timedelta(minutes=3)),                               # just ended: the job already told the user
    dict(age=timedelta(days=8)),                                  # too old to matter
])
async def test_jobs_that_need_no_follow_up_raise_nothing(execution_db, make):
    async with execution_db() as db:
        await add_task(db, "job-x", **make)
        await db.commit()
    assert await det.job_followups(ctx()) == []


async def test_an_unknown_reason_is_still_reported_honestly(execution_db):
    async with execution_db() as db:
        await add_task(db, "job-2", reason="something_new")
        await db.commit()
    [found] = await det.job_followups(ctx())
    assert found.candidate.evidence[1].key == "job.reason.other" and found.candidate.priority == "normal"


# ── scheduled tasks that keep failing ────────────────────────────────────────

async def add_schedule(db, name, *, failures=0, paused=None, enabled=True):
    task = ScheduledTask(name=name, prompt="Check the weekly numbers", schedule_kind="interval", interval_s=3600,
                         enabled=enabled, consecutive_failures=failures, paused_reason=paused)
    db.add(task)
    await db.flush()
    for n in range(4):
        db.add(ScheduledTaskRun(task_id=task.id, started_at=NOW - timedelta(hours=n), outcome="error",
                                reason=f"provider timeout {n}"))
    return task


async def test_a_paused_or_repeatedly_failing_schedule_is_raised(execution_db):
    async with execution_db() as db:
        paused = await add_schedule(db, "Weekly digest", failures=3, paused="3 failures in a row")
        failing = await add_schedule(db, "Morning check", failures=2)
        await add_schedule(db, "Healthy", failures=1)
        await add_schedule(db, "Off", failures=5, enabled=False)
        await add_schedule(db, det.HEARTBEAT_NAME, failures=9, paused="x")
        await db.commit()
        ids = (paused.id, failing.id)
    found = {f.candidate.params["name"]: f.candidate for f in await det.scheduled_problems(ctx())}
    assert set(found) == {"Weekly digest", "Morning check"}
    assert found["Weekly digest"].priority == "high" and found["Morning check"].priority == "normal"
    assert found["Weekly digest"].source_key == f"sched:{ids[0]}"
    runs = [e for e in found["Weekly digest"].evidence if e.key == "sched.run"]
    assert len(runs) == 3 and runs[0].quote.startswith("provider timeout")       # newest three, as quotes
    assert "Weekly digest" in found["Weekly digest"].goal and "Check the weekly numbers" in found["Weekly digest"].goal


async def test_a_schedule_that_fails_again_is_a_new_finding(execution_db):
    async with execution_db() as db:
        task = await add_schedule(db, "Nightly", failures=2)
        await db.commit()
        task_id = task.id
    first = (await det.scheduled_problems(ctx()))[0].candidate.fingerprint
    async with execution_db() as db:
        (await db.get(ScheduledTask, task_id)).consecutive_failures = 3
        await db.commit()
    assert (await det.scheduled_problems(ctx()))[0].candidate.fingerprint != first


# ── web pages ────────────────────────────────────────────────────────────────

PAGE = "\n".join(f"Line {n} of the pricing page" for n in range(40)) + "\nPro plan: $10 per month"
CHANGED = PAGE.replace("$10", "$12")


def fetcher(pages):
    seen = []

    async def fetch(url):
        seen.append(url)
        page = pages[0]
        if isinstance(page, Exception):
            raise page
        return page
    fetch.seen = seen
    return fetch


async def add_watch(db, kind="web", target="https://example.com/pricing", **over):
    watch = ProactiveWatch(kind=kind, target=target, label="Pricing", interval_s=3600, **over)
    db.add(watch)
    await db.flush()
    return watch.id


async def get_watch(execution_db, watch_id):
    async with execution_db() as db:
        return await db.get(ProactiveWatch, watch_id)


def test_small_noise_is_not_a_change_but_a_price_edit_is():
    long_page = "\n".join(f"row {n}" for n in range(300))
    assert not det.significant(long_page + "\nUpdated 10:01", long_page + "\nUpdated 10:02")   # a clock
    assert det.significant(PAGE, CHANGED)
    assert det.significant("a\nb", "a\nc")                        # short pages: one edited line counts
    assert not det.significant(PAGE, PAGE)


async def test_the_first_look_is_remembered_not_reported(execution_db):
    async with execution_db() as db:
        watch_id = await add_watch(db)
        await db.commit()
    assert await det.web_changes(ctx(fetch=fetcher([PAGE]))) == []
    row = await get_watch(execution_db, watch_id)
    assert row.snapshot == {"text": PAGE} and row.last_checked_at == NOW and row.last_error is None


async def test_a_real_change_is_reported_with_quotes_and_the_baseline_moves_only_on_ack(execution_db):
    async with execution_db() as db:
        watch_id = await add_watch(db, snapshot={"text": PAGE}, last_hash=det._digest(PAGE),
                                   last_checked_at=NOW - timedelta(hours=2))
        await db.commit()
    [found] = await det.web_changes(ctx(fetch=fetcher([CHANGED])))
    c = found.candidate
    assert c.kind == "web_change" and c.source_key == f"watch:{watch_id}" and c.notify is True
    quotes = {(e.key, e.quote) for e in c.evidence if e.quote}
    assert ("web.added", "Pro plan: $12 per month") in quotes and ("web.removed", "Pro plan: $10 per month") in quotes
    assert c.evidence[0].params["added"] == 1 and "example.com/pricing" in c.goal
    assert "not instructions" in c.goal                                   # page text is data
    assert (await get_watch(execution_db, watch_id)).snapshot == {"text": PAGE}    # not moved yet
    await found.ack()
    row = await get_watch(execution_db, watch_id)
    assert row.snapshot == {"text": CHANGED} and row.last_item_at == NOW


async def test_a_change_inside_the_cooldown_is_held_not_lost(execution_db):
    async with execution_db() as db:
        watch_id = await add_watch(db, snapshot={"text": PAGE}, last_hash=det._digest(PAGE),
                                   last_checked_at=NOW - timedelta(hours=2), last_item_at=NOW - timedelta(hours=5))
        await db.commit()
    assert await det.web_changes(ctx(fetch=fetcher([CHANGED]))) == []
    assert (await get_watch(execution_db, watch_id)).snapshot == {"text": PAGE}    # still waiting to be reported
    [found] = await det.web_changes(ctx(now=NOW + timedelta(hours=20), fetch=fetcher([CHANGED])))
    assert found.candidate.evidence[0].params["added"] == 1                        # raised once the day is up


async def test_a_dead_page_is_a_status_not_a_finding(execution_db):
    async with execution_db() as db:
        watch_id = await add_watch(db, snapshot={"text": PAGE})
        await db.commit()
    assert await det.web_changes(ctx(fetch=fetcher([RuntimeError("fetch failed: timeout")]))) == []
    row = await get_watch(execution_db, watch_id)
    assert row.last_error == "fetch failed: timeout" and row.consecutive_errors == 1
    await det.web_changes(ctx(now=NOW + timedelta(hours=2), fetch=fetcher([PAGE])))
    assert (await get_watch(execution_db, watch_id)).consecutive_errors == 0        # recovered


async def test_only_due_enabled_watches_are_fetched(execution_db):
    async with execution_db() as db:
        await add_watch(db, target="https://due.example/", last_checked_at=NOW - timedelta(hours=2))
        await add_watch(db, target="https://fresh.example/", last_checked_at=NOW - timedelta(minutes=5))
        await add_watch(db, target="https://off.example/", enabled=False)
        await db.commit()
    fetch = fetcher([PAGE])
    await det.web_changes(ctx(fetch=fetch))
    assert fetch.seen == ["https://due.example/"]


# ── folders ──────────────────────────────────────────────────────────────────

async def test_new_files_are_reported_by_name_and_hidden_ones_are_not(execution_db, tmp_path):
    tmp_path = tmp_path / "watched"               # the test database lives in tmp_path itself
    tmp_path.mkdir()
    (tmp_path / "old.txt").write_text("x")
    async with execution_db() as db:
        watch_id = await add_watch(db, kind="folder", target=str(tmp_path))
        await db.commit()
    assert await det.folder_changes(ctx(workspace=tmp_path)) == []                  # first look
    (tmp_path / "invoice.pdf").write_text("x")
    (tmp_path / ".DS_Store").write_text("x")
    async with execution_db() as db:
        (await db.get(ProactiveWatch, watch_id)).last_checked_at = NOW - timedelta(hours=2)
        await db.commit()
    [found] = await det.folder_changes(ctx(workspace=tmp_path))
    c = found.candidate
    assert c.kind == "folder_change" and c.params["count"] == 1
    assert [e.quote for e in c.evidence if e.key == "folder.file"] == ["invoice.pdf"]
    assert str(tmp_path.resolve()) in c.goal
    await found.ack()
    assert sorted((await get_watch(execution_db, watch_id)).snapshot["names"]) == ["invoice.pdf", "old.txt"]


async def test_a_folder_outside_the_workspace_is_never_read(execution_db, tmp_path):
    workspace, outside = tmp_path / "work", tmp_path / "private"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("x")
    link = workspace / "sneaky"
    link.symlink_to(outside)
    async with execution_db() as db:
        ids = [await add_watch(db, kind="folder", target=str(outside)),
               await add_watch(db, kind="folder", target=str(link))]      # a symlink out of the workspace
        await db.commit()
    assert await det.folder_changes(ctx(workspace=workspace)) == []
    for watch_id in ids:
        row = await get_watch(execution_db, watch_id)
        assert row.last_error == "outside_workspace" and row.snapshot is None     # never even listed
    assert det.inside(None, str(workspace)) is None


async def test_deleted_files_update_the_snapshot_quietly(execution_db, tmp_path):
    tmp_path = tmp_path / "watched"
    tmp_path.mkdir()
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    async with execution_db() as db:
        watch_id = await add_watch(db, kind="folder", target=str(tmp_path), snapshot={"names": ["a.txt", "b.txt", "gone.txt"]})
        await db.commit()
    assert await det.folder_changes(ctx(workspace=tmp_path)) == []
    assert (await get_watch(execution_db, watch_id)).snapshot == {"names": ["a.txt", "b.txt"]}


async def test_detectors_stay_read_only_and_model_free(execution_db):
    """Every detector module import: no adapter, no network client besides the injected fetch."""
    import inspect
    source = inspect.getsource(det)
    for forbidden in ("build_adapter", "llm_factory", "adapter.chat", "httpx"):
        assert forbidden not in source
    assert select  # (sqlalchemy select is the only data access)
