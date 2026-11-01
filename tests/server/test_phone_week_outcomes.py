"""IPB (v0.1.64): `status.snapshot.week` and `status.snapshot.outcomes` for iPhone 1.0's part B
(docs/plans/0164/IPB-frame-list.md §2). Both come from persisted rows only, so a restart never resets
them: the last 7 local days of replies, tasks and cards asked, and today's and this week's finished
tasks with their checks, cost and whether they needed you."""
from datetime import UTC, datetime, timedelta

import pytest

from server.db.models import ApprovalEvent, Judgment, Run, UsageLedger
from server.db.task_models import CompanionTask, TaskAttempt, TaskRevision
from server.services import background_jobs, phone_stats
from server.services.background_jobs import Job

# Local noon on a fixed day, so a run near midnight can't move a row across days.
NOON = datetime(2026, 10, 15, 12, 0).astimezone()
NOW = NOON.timestamp()
MIDNIGHT = NOON.replace(hour=0)
PRICED = "claude-sonnet-5-5"            # $2 per million in, $10 per million out (arslan/llm/prices.py)


def utc(local: datetime) -> datetime:
    """A local moment as the naive UTC the rows store."""
    return local.astimezone(UTC).replace(tzinfo=None)


def day(offset: int) -> str:
    return (MIDNIGHT + timedelta(days=offset)).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _clean():
    phone_stats._reset_for_tests()
    background_jobs._jobs.clear()
    yield
    phone_stats._reset_for_tests()
    background_jobs._jobs.clear()


_run_ids = iter(range(1, 10_000))


def run(at: datetime, *, kind="live", tokens=(None, None), model=PRICED, estimated=False, conversation="c") -> Run:
    tin, tout = tokens
    return Run(id=next(_run_ids), conversation_id=conversation, user_message="x", started_at=utc(at), created_at=utc(at),
               status="recorded", kind=kind, model=model, tokens_in=tin, tokens_out=tout, tokens_estimated=estimated,
               task_tokens=(tin or 0) + (tout or 0) or 10)


def task(task_id: str, finished: datetime, *, phase="succeeded", reason=None, goal="Sort the invoices",
         checks=(), results=(), runs=(), driver="background", conversation=None) -> list:
    spec = {"instruction": goal, "acceptance": [{"id": c, "description": c, "evaluator": "model"}
                                                for c in (*checks, "answer-delivered")]}
    return [CompanionTask(id=task_id, conversation_id=conversation or f"conv-{task_id}", attempt_id=f"a-{task_id}",
                          budget={}, privacy={"driver": {"kind": driver}}, phase=phase, pause_reason=reason,
                          results=[{"check_id": c, "status": s, "evaluator": "model"} for c, s in results],
                          created_at=utc(finished - timedelta(minutes=5)), updated_at=utc(finished)),
            TaskRevision(task_id=task_id, revision=1, spec=spec),
            TaskAttempt(id=f"a-{task_id}", task_id=task_id, number=1, spec_revision=1, run_ids=[r.id for r in runs])]


def asked(at: datetime, decided_by: str, job_id=None) -> ApprovalEvent:
    return ApprovalEvent(created_at=utc(at), conversation_id="c", job_id=job_id, kind="command", target="ls",
                         mode="standard", decided_by=decided_by, decision="allow")


async def _add(client, rows):
    async with client.db_maker() as db:
        for row in rows:
            db.add(row)
            await db.flush()
        await db.commit()


async def _blocks(client) -> dict:
    async with client.db_maker() as db:
        return await phone_stats.blocks(db, now=NOW)


# ------------------------------------------------------------------ week

async def test_the_week_is_seven_local_days_oldest_first_counted_from_rows(client):
    first = MIDNIGHT - timedelta(days=6)
    task_today, task_yesterday = run(NOON - timedelta(hours=1)), run(NOON - timedelta(days=1))
    host_turn = run(NOON - timedelta(hours=2))
    rows = [
        run(first),                                        # the first second of the window
        run(first - timedelta(seconds=1)),                 # the last second before it
        run(NOON), run(NOON - timedelta(hours=3)),         # two replies today
        run(NOON, kind="replay"),                          # a replay is never counted
        task_today, task_yesterday, host_turn,
        *task("t1", NOON, runs=[task_today]),
        *task("t2", NOON - timedelta(days=1), runs=[task_yesterday]),
        *task("h1", NOON, driver="host", runs=[host_turn]),   # a turn's own task: still a reply
        asked(NOON, "user"), asked(NOON, "expired"),
        asked(NOON, "rule"), asked(NOON, "away"),          # nobody had these in front of them
        asked(NOON - timedelta(days=3), "user"),
    ]
    await _add(client, rows)
    week = (await _blocks(client))["week"]
    assert [d["day"] for d in week] == [day(k) for k in range(-6, 1)], "oldest first, the last item is today"
    assert week[0]["counts"] == [1, 0, 0]
    assert week[3]["counts"] == [0, 0, 1]
    assert week[5]["counts"] == [0, 1, 0]
    assert week[6]["counts"] == [3, 1, 2], "replies (host turn included), tasks, cards asked"
    assert sum(d["counts"][0] for d in week) == 4


async def test_a_day_with_nothing_still_has_its_item(client):
    week = (await _blocks(client))["week"]
    assert week == [{"day": day(k), "counts": [0, 0, 0]} for k in range(-6, 1)]


# ------------------------------------------------------------------ outcomes

async def test_finished_tasks_newest_first_with_their_state_checks_cost_and_whether_they_needed_you(client):
    paid_in, paid_out = run(NOON, tokens=(1_000_000, 0)), run(NOON, tokens=(0, 500_000))   # $2 + $5
    unpriced = run(NOON - timedelta(days=2), tokens=(100, 100), estimated=True)
    rows = [
        paid_in, paid_out, unpriced,
        *task("done", NOON - timedelta(minutes=1), goal="Sort the invoices\ninto one   table" + " x" * 60,
              checks=("c1", "c2"), results=[("c1", "passed"), ("c2", "not_applicable"), ("answer-delivered", "passed")],
              runs=[paid_in, paid_out]),
        *task("budget", NOON - timedelta(days=2), phase="waiting_user", reason="task_budget_exhausted",
              checks=("c1",), results=[("c1", "failed")], runs=[unpriced]),
        *task("stopped", NOON - timedelta(minutes=2), phase="cancelled", reason="user_cancelled"),
        *task("restart", NOON - timedelta(minutes=3), phase="cancelled", reason="process_interrupted"),
        *task("missed", NOON - timedelta(minutes=4)),       # done by its answer, but the judge says no
        *task("unsure", NOON - timedelta(minutes=5)),       # the judge's no is too close to call
        *task("partly", NOON - timedelta(minutes=6), phase="failed", checks=("c1", "c2"),
              results=[("c1", "passed"), ("c2", "failed"), ("answer-delivered", "passed")]),
        *task("running", NOON, phase="running"),            # running tasks are left out
        *task("queued", NOON, phase="queued"),
        *task("live", NOON, phase="waiting_user"),          # its job has not finished yet
        *task("turn", NOON, driver="host"),                 # a turn's own task is not a task
        *task("old", MIDNIGHT - timedelta(days=6, seconds=1)),
        Judgment(point="job.accomplished", mode="active", state={}, state_hash="h", verdict=False,
                 probability=0.95, ref="missed"),
        Judgment(point="job.accomplished", mode="active", state={}, state_hash="h", verdict=False,
                 probability=0.5, ref="unsure"),
        asked(NOON, "user", job_id="done"), asked(NOON, "rule", job_id="budget"),
    ]
    background_jobs._jobs["live"] = Job("live", "conv-live", "goal", [], phase="running")
    await _add(client, rows)
    outcomes = (await _blocks(client))["outcomes"]
    today, week = outcomes["today"], outcomes["week"]
    assert [t["conversation_id"] for t in today["tasks"]] == [
        "conv-done", "conv-stopped", "conv-restart", "conv-missed", "conv-unsure", "conv-partly"]
    assert [t["conversation_id"] for t in week["tasks"]] == [t["conversation_id"] for t in today["tasks"]] + ["conv-budget"]
    by = {t["conversation_id"][5:]: t for t in week["tasks"]}
    assert by["done"] == {"conversation_id": "conv-done", "state": "done", "checks_passed": 2, "checks_total": 2,
                          "needed_you": True, "spent_usd": 7.0,
                          "title": "Sort the invoices into one table" + " x" * 23 + " …"}
    assert len(by["done"]["title"]) == 80
    assert by["budget"] == {"conversation_id": "conv-budget", "title": "Sort the invoices", "state": "unfinished",
                            "checks_passed": 0, "checks_total": 1, "needed_you": False}, "nothing priced: no spent_usd"
    assert {k: by[k]["state"] for k in ("stopped", "restart", "missed", "unsure", "partly")} == {
        "stopped": "failed", "restart": "unfinished", "missed": "unfinished", "unsure": "done", "partly": "unfinished"}
    assert (by["partly"]["checks_passed"], by["partly"]["checks_total"]) == (1, 2)


async def test_what_was_spent_in_each_range_and_what_no_listed_task_spent(client):
    paid = run(NOON, tokens=(1_000_000, 0))                                 # $2, a task's
    rows = [
        paid, run(NOON - timedelta(hours=1), tokens=(0, 100_000)),         # $1, a reply's
        run(NOON - timedelta(days=3), tokens=(500_000, 0)),                # $1, this week only
        run(MIDNIGHT - timedelta(days=7), tokens=(1_000_000, 0)),          # before the week
        UsageLedger(ts=utc(NOON), scope="router", model=PRICED, tokens_in=250_000, tokens_out=0, tokens_total=250_000),
        *task("t", NOON, runs=[paid]),
    ]
    await _add(client, rows)
    outcomes = (await _blocks(client))["outcomes"]
    assert (outcomes["today"]["spent_usd"], outcomes["today"]["other_spent_usd"]) == (3.5, 1.5)
    assert (outcomes["week"]["spent_usd"], outcomes["week"]["other_spent_usd"]) == (4.5, 2.5)
    assert "spent_partial" not in outcomes["today"]
    await _add(client, [run(NOON, tokens=(10, 10), estimated=True)])
    phone_stats._reset_for_tests()
    assert (await _blocks(client))["outcomes"]["today"]["spent_partial"] is True, "some use had no price"


async def test_other_spending_never_goes_below_zero(client):
    # A task's run from yesterday is counted in the task, but not in today's range.
    early = run(NOON - timedelta(days=1), tokens=(1_000_000, 0))
    await _add(client, [early, *task("t", NOON, runs=[early])])
    today = (await _blocks(client))["outcomes"]["today"]
    assert (today["spent_usd"], today["tasks"][0]["spent_usd"], today["other_spent_usd"]) == (0.0, 2.0, 0.0)


async def test_each_set_holds_at_most_the_cap_newest_first(client):
    assert phone_stats.TASK_CAP == 50
    rows = [row for k in range(51) for row in task(f"t{k:02d}", NOON - timedelta(minutes=k))]
    await _add(client, rows)
    tasks = (await _blocks(client))["outcomes"]["today"]["tasks"]
    assert [t["conversation_id"] for t in tasks] == [f"conv-t{k:02d}" for k in range(50)]


# ------------------------------------------------------------------ on the snapshot, and the cache

async def test_the_snapshot_carries_both_blocks(client, monkeypatch):
    monkeypatch.setattr(phone_stats.time, "time", lambda: NOW)
    await _add(client, [run(NOON)])
    got = (await client.get("/api/v1/phone/status")).json()
    assert got["week"][-1] == {"day": day(0), "counts": [1, 0, 0]}
    assert set(got["outcomes"]) == {"today", "week"}


async def test_the_blocks_are_cached_until_a_task_finishes_or_a_minute_passes(client, monkeypatch):
    builds = []
    real = phone_stats._build
    monkeypatch.setattr(phone_stats, "_build", lambda db, now: builds.append(now) or real(db, now))
    await _blocks(client)
    await _blocks(client)
    assert len(builds) == 1, "the Bridge reads this every 2 s"
    await _add(client, task("t", NOON))                    # a task finished
    assert [t["conversation_id"] for t in (await _blocks(client))["outcomes"]["today"]["tasks"]] == ["conv-t"]
    await _add(client, [asked(NOON, "user")])             # a card was asked
    assert (await _blocks(client))["week"][-1]["counts"][2] == 1
    assert len(builds) == 3
    async with client.db_maker() as db:
        await phone_stats.blocks(db, now=NOW + phone_stats.CACHE_SECONDS + 1)
    assert len(builds) == 4


# ------------------------------------------------------------------ the shared vectors

def _vector_snapshots() -> list[dict]:
    import json
    from pathlib import Path
    examples = json.loads((Path(__file__).resolve().parents[2] / "spec/mobile-bridge/vectors/messages.json").read_text())["examples"]
    return [e["envelope"]["body"] for e in examples if e["envelope"]["type"] == "status.snapshot" and "outcomes" in e["envelope"]["body"]]


def test_the_cap_is_the_one_a_vector_pins():
    assert max(len(s["outcomes"]["week"]["tasks"]) for s in _vector_snapshots()) == phone_stats.TASK_CAP


async def test_the_blocks_have_the_vectors_shape(client):
    paid = run(NOON, tokens=(1_000_000, 0))
    await _add(client, [paid, run(NOON, tokens=(10, 10), estimated=True),
                        *task("priced", NOON, checks=("c1",), runs=[paid]), *task("unpriced", NOON - timedelta(minutes=1))])
    got = await _blocks(client)
    vector = _vector_snapshots()[0]
    assert {tuple(d) for d in got["week"]} == {tuple(d) for d in vector["week"]} == {("day", "counts")}
    assert set(got["outcomes"]) == set(vector["outcomes"])
    assert set(got["outcomes"]["today"]) == set(vector["outcomes"]["week"]), "spent_partial included"
    shapes = sorted(map(sorted, got["outcomes"]["today"]["tasks"]))
    assert shapes == sorted(map(sorted, vector["outcomes"]["week"]["tasks"])), "one with spent_usd, one without"
