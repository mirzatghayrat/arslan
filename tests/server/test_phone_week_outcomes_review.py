"""IPB-1a follow-up (#647's effort=max review): what `week` and `outcomes` must never send, and what must
never take the snapshot down. F1: a deleted conversation's tasks. F2: an optional block that fails, and
characters a title must not carry. F3: a job that just finished. F4: a time zone other than UTC, across a DST
change. F5: only the goal reaches the phone, and only as the title."""
import json
import os
import time
from datetime import datetime, timedelta

import pytest

from server.db.models import Judgment
from server.services import background_jobs, phone_stats
from server.services.background_jobs import Job
from tests.server.test_phone_week_outcomes import MIDNIGHT, NOON, NOW, _add, _blocks, run, task, utc


@pytest.fixture(autouse=True)
def _clean():
    phone_stats._reset_for_tests()
    background_jobs._jobs.clear()
    yield
    phone_stats._reset_for_tests()
    background_jobs._jobs.clear()


def _ids(tasks: list[dict]) -> list[str]:
    return [t["conversation_id"] for t in tasks]


# ------------------------------------------------------------------ F1: a deleted conversation

async def test_a_deleted_conversations_tasks_are_never_sent(client):
    await _add(client, [*task("gone", NOON, goal="Pay the rent from the joint account"), *task("kept", NOON - timedelta(minutes=1))])
    assert _ids((await _blocks(client))["outcomes"]["week"]["tasks"]) == ["conv-gone", "conv-kept"]
    assert (await client.delete("/api/v1/conversations/conv-gone")).status_code == 200
    phone_stats._reset_for_tests()
    body = await _blocks(client)
    assert _ids(body["outcomes"]["week"]["tasks"]) == ["conv-kept"]
    assert "joint account" not in json.dumps(body)


# ------------------------------------------------------------------ F2: never down for an optional block

async def test_a_failing_block_is_left_out_and_the_snapshot_still_answers(client, monkeypatch):
    async def broken(db, now=None):
        raise RuntimeError("boom")
    monkeypatch.setattr(phone_stats, "blocks", broken)
    got = await client.get("/api/v1/phone/status")
    assert got.status_code == 200
    assert "week" not in got.json() and "outcomes" not in got.json() and got.json()["presence"] == "online"


async def test_a_title_carries_no_surrogate_control_or_format_character(client, monkeypatch):
    monkeypatch.setattr(phone_stats.time, "time", lambda: NOW)
    lone, bidi, zero_width, bell = chr(0xD800), chr(0x202E), chr(0x200B), chr(0x07)
    rows = task("odd", NOON, goal=f"Sort{lone} the {bidi}invoices{zero_width} now{bell}")
    rows[3].content = "sort the invoices"          # the message column can't hold a lone surrogate; the spec's JSON can
    await _add(client, rows)
    got = await client.get("/api/v1/phone/status")
    assert got.status_code == 200, "a lone surrogate used to fail the whole snapshot"
    assert got.json()["outcomes"]["today"]["tasks"][0]["title"] == "Sort the invoices now"


async def test_the_home_folder_in_a_goal_is_shown_as_a_tilde(client, monkeypatch, tmp_path):
    home = tmp_path / "Home"
    monkeypatch.setattr(phone_stats, "_home", lambda: home)
    await _add(client, [*task("path", NOON, goal=f"Summarise {home}/Documents/plan.md")])
    body = await _blocks(client)
    assert body["outcomes"]["today"]["tasks"][0]["title"] == "Summarise ~/Documents/plan.md"
    assert str(home) not in json.dumps(body)


# ------------------------------------------------------------------ F3: the cache and a job that just finished

async def test_a_job_that_just_finished_is_listed_at_once(client):
    job = Job("t", "conv-t", "goal", [], phase="running")
    background_jobs._jobs["t"] = job
    await _add(client, task("t", NOON))
    assert (await _blocks(client))["outcomes"]["today"]["tasks"] == [], "running: left out"
    job.phase = "finished"                                   # nothing in the database changes
    assert _ids((await _blocks(client))["outcomes"]["today"]["tasks"]) == ["conv-t"]


async def test_a_new_day_builds_again_even_within_the_minute(client):
    await _add(client, task("late", MIDNIGHT - timedelta(seconds=20)))
    async with client.db_maker() as db:
        before = await phone_stats.blocks(db, now=(MIDNIGHT - timedelta(seconds=10)).timestamp())
        after = await phone_stats.blocks(db, now=(MIDNIGHT + timedelta(seconds=20)).timestamp())
    assert _ids(before["outcomes"]["today"]["tasks"]) == ["conv-late"]
    assert after["outcomes"]["today"]["tasks"] == [], "yesterday's task left today's set at midnight"


# ------------------------------------------------------------------ the review's mutation survivors

async def test_the_review_survivors(client):
    replay = run(NOON, kind="replay", tokens=(1_000_000, 0))                 # $2: Progress counts evolution arms
    rows = [replay, *task("midnight", MIDNIGHT), *task("verifying", NOON, phase="verifying"), *task("judged", NOON),
            Judgment(point="job.accomplished", mode="active", state={}, state_hash="h", verdict=True, probability=0.9,
                     ref="judged"),
            Judgment(point="job.accomplished", mode="active", state={}, state_hash="h", verdict=False, probability=0.95,
                     ref="judged")]                                         # the newer verdict wins
    await _add(client, rows)
    today = (await _blocks(client))["outcomes"]["today"]
    assert _ids(today["tasks"]) == ["conv-judged", "conv-midnight"], "verifying is not finished; midnight is today"
    assert today["tasks"][0]["state"] == "unfinished"
    assert today["spent_usd"] == 2.0


# ------------------------------------------------------------------ F4: a time zone that isn't UTC, across DST

@pytest.fixture
def new_york():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"                   # DST ends on 2026-11-01
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


async def test_the_week_follows_the_macs_time_zone_across_a_dst_change(client, new_york):
    def at(*parts) -> datetime:
        return datetime(*parts).astimezone()                 # local, with that day's offset
    rows = [run(at(2026, 10, 28, 0, 0)),                     # the first second of the window (EDT)
            run(at(2026, 10, 27, 23, 59, 59)),               # the last second before it
            run(at(2026, 10, 30, 22, 0)),                    # 02:00 UTC on the 31st, still the 30th here
            run(at(2026, 11, 2, 23, 30)),                    # 04:30 UTC on the 3rd (EST), still the 2nd here
            run(at(2026, 11, 3, 9, 0)),
            *task("evening", at(2026, 11, 2, 21, 0))]        # 02:00 UTC on the 3rd: last night here, not today
    await _add(client, rows)
    async with client.db_maker() as db:
        body = await phone_stats.blocks(db, now=at(2026, 11, 3, 12, 0).timestamp())
    week = body["week"]
    assert body["outcomes"]["today"]["tasks"] == [] and _ids(body["outcomes"]["week"]["tasks"]) == ["conv-evening"]
    assert [d["day"] for d in week] == ["2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01",
                                        "2026-11-02", "2026-11-03"]
    assert [d["counts"][0] for d in week] == [1, 0, 1, 0, 0, 1, 1]
    assert utc(at(2026, 10, 28, 0, 0)) == datetime(2026, 10, 28, 4, 0), "EDT is UTC-4"


# ------------------------------------------------------------------ F5: only the goal leaves, only as the title

async def test_only_the_goal_reaches_the_phone_and_only_as_the_title(client):
    priced = run(NOON, tokens=(1_000_000, 0))
    priced.error_text, priced.user_message = "canary-error-text", "canary-user-message"
    rows = [priced, *task("t", NOON, goal="Goal canary-goal-text", checks=("c1",), runs=[priced],
                          results=[("c1", "passed")])]
    rows[2].spec["acceptance"][0]["description"] = "canary-acceptance"          # the TaskRevision's spec
    rows[1].results = [{"check_id": "c1", "status": "passed", "evaluator": "model", "evidence": [{"note": "canary-result"}]}]
    await _add(client, rows)
    body = await _blocks(client)
    text = json.dumps(body)
    for canary in ("canary-error-text", "canary-user-message", "canary-acceptance", "canary-result"):
        assert canary not in text
    assert text.count("canary-goal-text") == 2, "the title, in today's set and the week's"
    for item in body["outcomes"]["today"]["tasks"] + body["outcomes"]["week"]["tasks"]:
        assert set(item) == {"conversation_id", "title", "state", "checks_passed", "checks_total", "needed_you", "spent_usd"}
        assert "canary-goal-text" in item["title"]



# ------------------------------------------------------------------ #651 follow-up review (N1–N5)

@pytest.mark.parametrize("goal, title", [
    ("Read {home}/Documents/a.md", "Read ~/Documents/a.md"),
    ("Read {home}", "Read ~"),
    ("Read {home}, then stop", "Read ~, then stop"),
    ("Read {home}x/Documents/a.md", "Read {home}x/Documents/a.md"),          # another user whose name starts the same
    ("Read /Volumes/Disk{home}/a.md", "Read /Volumes/Disk{home}/a.md"),      # the home's path inside another path
    ("Read {upper}/Documents/a.md", "Read ~/Documents/a.md"),                # the same folder, typed in another case
])
def test_the_home_becomes_a_tilde_only_as_a_whole_path(monkeypatch, goal, title):
    home = "/Users/alice"
    monkeypatch.setattr(phone_stats, "_home", lambda: home)
    fill = {"home": home, "upper": home.upper()}
    assert phone_stats._title(goal.format(**fill)) == title.format(**fill)


def test_a_root_home_is_never_replaced(monkeypatch):
    monkeypatch.setattr(phone_stats, "_home", lambda: "/")
    assert phone_stats._title("Copy /etc/hosts to /tmp/a") == "Copy /etc/hosts to /tmp/a"


def test_joiners_stay_in_a_title():
    zwj, zwnj = chr(0x200D), chr(0x200C)
    family = chr(0x1F468) + zwj + chr(0x1F469) + zwj + chr(0x1F467)
    assert phone_stats._title(f"Photos of the {family} and {zwnj}x") == f"Photos of the {family} and {zwnj}x"


async def test_a_new_message_builds_again(client):
    await _add(client, task("t", NOON))
    first = await _blocks(client)
    from server.db.models import ArslanMessage
    async with client.db_maker() as db:                       # the conversation is emptied, nothing else changes
        from sqlalchemy import delete
        await db.execute(delete(ArslanMessage).where(ArslanMessage.conversation_id == "conv-t"))
        db.add(ArslanMessage(conversation_id="conv-other", role="user", content="hi"))
        await db.commit()
    assert _ids(first["outcomes"]["today"]["tasks"]) == ["conv-t"]
    assert (await _blocks(client))["outcomes"]["today"]["tasks"] == []


async def test_a_failing_block_logs_only_its_class(client, monkeypatch, caplog):
    async def broken(db, now=None):
        raise RuntimeError("canary-detail /Users/alice/secret.txt")
    monkeypatch.setattr(phone_stats, "blocks", broken)
    with caplog.at_level("WARNING"):
        assert (await client.get("/api/v1/phone/status")).status_code == 200
    text = caplog.text
    assert "RuntimeError" in text and "canary-detail" not in text and "secret.txt" not in text


async def test_a_running_jobs_goal_never_fails_the_snapshot(client):
    lone, bidi = chr(0xD800), chr(0x202E)
    background_jobs._jobs["j"] = Job("j", "conv-j", f"Tidy{lone} the {bidi}downloads", [], phase="running", step=f"run{lone}")
    got = await client.get("/api/v1/phone/status")
    assert got.status_code == 200
    assert got.json()["jobs"][0]["goal"] == "Tidy the downloads"


async def test_an_unpriced_item_with_no_tokens_leaves_spent_whole(client):
    nothing = run(NOON, model="no-price-model")
    nothing.task_tokens = 0
    await _add(client, [nothing, run(NOON, tokens=(1_000_000, 0))])
    today = (await _blocks(client))["outcomes"]["today"]
    assert today["spent_usd"] == 2.0 and "spent_partial" not in today
