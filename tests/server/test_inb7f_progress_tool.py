"""INB7-f (v0.1.64): "how is it going" in any conversation, answered from the records (progress_report).

The INB card's brief has four lines: done today, running, stuck, waiting on you. Each counts conversations, projects and
scheduled tasks, never rows, and each comes from one function in server/services/progress.py, so the page and the tool can't
drift. Waiting on you is the badge's own function (`waiting_on_user`, GET /proactive/summary). Progress shows no done / running
/ stuck yet; the tool and a later page read the same `progress.brief`. The lines are template sentences: no model, and no number
that isn't one of the four counts. The tool reads only, is not in the default table and is found on demand (K7).
"""
import re
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from server.db.companion_models import ConversationContext, Project
from server.db.models import ArslanMessage, CompanionTask, Run, ScheduledTask, ScheduledTaskRun
from server.services import approvals, progress


async def _add(client, *rows):
    async with client.db_maker() as db:
        db.add_all(rows)
        await db.commit()


def _chat(cid, first="hello there"):
    return [ArslanMessage(conversation_id=cid, role="user", content=first),
            ArslanMessage(conversation_id=cid, role="arslan", content="REPLY-BODY")]


def _job(id_, cid, phase, reason=None, hours_ago=0.5, driver="background"):
    return CompanionTask(id=id_, conversation_id=cid, attempt_id=f"attempt-{id_}", budget={},
                         privacy={"driver": {"kind": driver}}, phase=phase, pause_reason=reason,
                         updated_at=datetime.utcnow() - timedelta(hours=hours_ago))


def _run(cid, status, error=None, hours_ago=0.0, kind="host"):
    at = datetime.utcnow() - timedelta(hours=hours_ago)
    return Run(conversation_id=cid, kind=kind, status=status, error_kind=error, created_at=at, started_at=at,
               ended_at=None if status == "recording" else at)


def _task(id_, **over):
    fields = dict(id=id_, name=f"task {id_}", prompt="p", schedule_kind="interval", interval_s=3600, enabled=True,
                  consecutive_failures=0)
    fields.update(over)
    return ScheduledTask(**fields)


async def _tool() -> dict:
    from server.registry.executors import EXECUTORS
    return await EXECUTORS["progress_report"].execute({})


def _ids(line: dict) -> list:
    return [(item["kind"], item["id"]) for item in line["items"]]


async def test_waiting_on_you_is_the_badges_own_count(client, monkeypatch):
    """The page's 「要你做」 tile and the sidebar badge read GET /proactive/summary; the tool reads the same function."""
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "chat-card"}])
    await _add(client, Project(id="p1", name="Home"), _task(1, enabled=False, paused_reason="3 failures"))
    await _add(client, ConversationContext(id="chat-p", project_id="p1"), *_chat("chat-card"), *_chat("chat-p"))
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "chat-card"},
                                                           {"call_id": "c2", "conversation_id": "chat-p"}])
    page = (await client.get("/api/v1/proactive/summary")).json()["waiting"]
    got = (await _tool())["waiting_on_you"]
    assert page["count"] == got["count"] == 3
    assert _ids(got) == ([("conversation", cid) for cid in page["conversations"]]
                         + [("project", pid) for pid in page["projects"]]
                         + [("scheduled_task", tid) for tid in page["scheduled"]])


async def test_each_line_counts_conversations_projects_and_tasks_from_the_records(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    await _add(client, Project(id="p1", name="Home"),
               _task(1, enabled=False, paused_reason="3 failures"), _task(2), _task(3, enabled=False))
    await _add(client, ConversationContext(id="chat-p1", project_id="p1"), ConversationContext(id="chat-p2", project_id="p1"),
               *_chat("chat-done", "write the weekly report"), _run("chat-done", "recorded"),
               *_chat("chat-old"), _run("chat-old", "recorded", hours_ago=30),            # yesterday: not done today
               *_chat("chat-job"), _job("j-run", "chat-job", "running"),                     # a job at work
               *_chat("chat-turn"), _run("chat-turn", "recording"),                         # a turn at work
               *_chat("chat-p1"), _job("j-p1", "chat-p1", "queued"),                        # a project's two at work
               *_chat("chat-p2"), _run("chat-p2", "recording"),
               *_chat("chat-fail"), _job("j-fail", "chat-fail", "failed"),
               *_chat("chat-err"), _run("chat-err", "recorded", error="provider_error"),
               *_chat("chat-blocked"), _job("j-blocked", "chat-blocked", "waiting_user", "task_validation_failed"),
               ScheduledTaskRun(task_id=2, outcome="ok", started_at=datetime.utcnow(), finished_at=datetime.utcnow()))
    brief = await _tool()
    assert brief["ok"] is True
    assert _ids(brief["done_today"]) == [("conversation", "chat-done"), ("scheduled_task", 2)]
    assert _ids(brief["running"]) == [("conversation", "chat-job"), ("conversation", "chat-turn"), ("project", "p1")]
    assert _ids(brief["stuck"]) == [("conversation", "chat-blocked"), ("conversation", "chat-err"),
                                    ("conversation", "chat-fail"), ("scheduled_task", 1)]
    assert {item["id"]: item["why"] for item in brief["stuck"]["items"]} == {
        "chat-blocked": "blocked", "chat-err": "failed", "chat-fail": "failed", 1: "paused"}
    assert brief["running"]["count"] == 3                     # chat-p1 and chat-p2 are one project
    # Titles are what the sidebar shows (the opening line) and the names the user gave; no message is quoted beyond that.
    titles = {item["id"]: item["title"] for line in ("done_today", "running", "stuck") for item in brief[line]["items"]}
    assert titles["chat-done"] == "write the weekly report"
    assert titles["p1"] == "Home" and titles[1] == "task 1"
    assert "REPLY-BODY" not in str(brief)


async def test_done_today_counts_only_clean_work(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    # "Today" starts at local midnight; the job is stored half an hour ago, which is yesterday between 00:00 and 00:30.
    # Pin the day's start an hour back so the test doesn't depend on the time it runs.
    monkeypatch.setattr(progress, "today_start", lambda now=None: datetime.utcnow() - timedelta(hours=1))
    await _add(client, _task(2), _task(4))
    await _add(client, *_chat("chat-done"), _run("chat-done", "recorded"),
               *_chat("chat-err"), _run("chat-err", "recorded", error="provider_error"),
               *_chat("chat-job"), _job("j-ok", "chat-job", "succeeded"),
               *_chat("chat-stop"), _run("chat-stop", "cancelled"),
               ScheduledTaskRun(task_id=2, outcome="ok", started_at=datetime.utcnow()),
               ScheduledTaskRun(task_id=4, outcome="error", started_at=datetime.utcnow()))
    assert _ids((await _tool())["done_today"]) == [("conversation", "chat-done"), ("conversation", "chat-job"),
                                                   ("scheduled_task", 2)]


async def test_three_things_in_one_conversation_count_once(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    await _add(client, *_chat("chat-three"), _job("j1", "chat-three", "failed", hours_ago=2),
               _job("j2", "chat-three", "cancelled", "process_interrupted", hours_ago=1),
               _run("chat-three", "interrupted"),
               *_chat("chat-two"), _job("j3", "chat-two", "running"), _run("chat-two", "recording"))
    brief = await _tool()
    assert (brief["stuck"]["count"], _ids(brief["stuck"])) == (1, [("conversation", "chat-three")])
    assert brief["stuck"]["items"][0]["why"] == "interrupted"      # a restart's cut says so first
    assert (brief["running"]["count"], _ids(brief["running"])) == (1, [("conversation", "chat-two")])


async def test_a_later_job_that_got_done_unsticks_its_conversation(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    await _add(client, *_chat("chat-a"), _job("j1", "chat-a", "failed", hours_ago=3), _job("j2", "chat-a", "succeeded", hours_ago=1),
               *_chat("chat-b"), _run("chat-b", "recorded", error="provider_error", hours_ago=2), _run("chat-b", "recorded", hours_ago=1),
               *_chat("chat-c"), _job("j3", "chat-c", "failed", hours_ago=24 * 8))      # older than a week
    assert (await _tool())["stuck"]["count"] == 0


async def test_waiting_on_your_answer_is_not_stuck(client, monkeypatch):
    """The card: waiting_user counts as stuck only when it isn't waiting on the user's answer."""
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    rows = [*_chat("chat-ask"), _job("j1", "chat-ask", "waiting_user", "task_input_required"),
            *_chat("chat-review"), _job("j2", "chat-review", "waiting_user", "acceptance_review_required"),
            *_chat("chat-budget"), _job("j3", "chat-budget", "waiting_user", "task_budget_exhausted")]
    await _add(client, *rows)
    brief = await _tool()
    assert _ids(brief["stuck"]) == [("conversation", "chat-budget")]
    assert brief["stuck"]["items"][0]["why"] == "blocked"


async def test_a_restart_cut_counts_as_stuck_and_your_own_stop_says_stopped(client, monkeypatch):
    """INB7-1 (#601) records the restart's own reason when it happens; nothing is worked out from the messages."""
    from server.services import background_jobs, run_reaper, runtime_messages
    from server.services.task_repository import repository
    from tests.server.test_task_repository import spec
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    monkeypatch.setattr(runtime_messages, "selected_locale", AsyncMock(return_value="en"))
    monkeypatch.setattr(background_jobs.desktop_status, "push", lambda *a, **k: None)
    await _add(client, *_chat("conv-job-cut"), *_chat("conv-job-mine"), *_chat("chat-turn"), _run("chat-turn", "recording"))
    async with repository() as repo:
        for identity in ("job-cut", "job-mine"):
            created = await repo.create(spec(identity, instruction=f"Goal of {identity}"), f"conv-{identity}",
                                        privacy={"driver": {"kind": "background"}})
            await repo.start(identity, created["version"])
        await repo.cancel("job-mine")                          # the user stops this one before the restart
    before = await _tool()
    assert _ids(before["running"]) == [("conversation", "chat-turn"), ("conversation", "conv-job-cut")]
    async with repository() as repo:                           # what a restart finds
        await repo.recover_interrupted()
    await run_reaper.mark_interrupted_runs()
    assert await background_jobs.report_interrupted() == 1
    after = await _tool()
    assert after["running"]["count"] == 0
    assert {item["id"]: item["why"] for item in after["stuck"]["items"]} == {
        "chat-turn": "interrupted", "conv-job-cut": "interrupted", "conv-job-mine": "stopped"}


async def test_the_lines_say_only_the_counts(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "chat-2026"}])
    await _add(client, *_chat("chat-2026", "plan 3 trips for 2027"), _run("chat-2026", "recorded"),
               *_chat("chat-9"), _job("j9", "chat-9", "failed"), *_chat("chat-7"), _run("chat-7", "recording"),
               _task(5, name="report 42", enabled=False, paused_reason="3 failures"))
    brief = await _tool()
    counts = [brief[key]["count"] for key in ("done_today", "running", "stuck", "waiting_on_you")]
    assert counts == [1, 1, 2, 2]
    assert len(brief["lines"]) == 4
    for line, count in zip(brief["lines"], counts):
        assert [int(n) for n in re.findall(r"\d+", line)] == [count], line


async def test_a_long_list_is_cut_and_says_how_many_more(client, monkeypatch):
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    rows = []
    for n in range(progress.LIST_CAP + 3):
        rows += [*_chat(f"chat-{n:02d}"), _run(f"chat-{n:02d}", "recording")]
    await _add(client, *rows)
    running = (await _tool())["running"]
    assert (running["count"], len(running["items"]), running["more"]) == (progress.LIST_CAP + 3, progress.LIST_CAP, 3)


async def test_it_is_a_read_the_model_finds_on_demand(client):
    from server.orchestrator import arslan, on_demand, parallel_reads, tool_loop
    from server.registry import tool_defs
    from server.services import task_service
    traits = tool_defs.TRAITS["progress_report"]
    assert (traits.effect, traits.parallel, traits.outside, traits.saves) == ("read", True, False, False)
    assert "progress_report" in parallel_reads.READS and "progress_report" in task_service._READ_TOOLS
    assert await task_service.effect_of("progress_report", {}) == "read"
    shown = {t["key"] for t in await arslan._arslan_tools()}
    reachable = [t for t in await arslan._callable_tools() if t["key"] not in shown]
    assert "progress_report" not in shown and "progress_report" not in arslan.RESIDENT
    assert on_demand.find("overall progress", reachable, tool_loop._tool_params)["tools"][0]["name"] == "progress_report"
    schema = tool_defs.SCHEMAS["progress_report"]
    assert schema == {"type": "object", "properties": {}, "additionalProperties": False}
    description = next(t.description for t in tool_defs.TOOLS if t.name == "progress_report")
    assert len(re.findall(r"[.!?](?:\s|$)", description)) <= 2


async def test_temporary_no_memory_and_quick_conversations_never_reach_another_conversations_model(client, monkeypatch):
    """#862 review: what other conversations may read follows conversation_search's rule (temporary and "don't use memory"
    conversations are never read), and the sidebar's (a quick question is in no list). Left out of the counts too: a count
    with no title would still tell another conversation's model they exist and what state they are in."""
    monkeypatch.setattr(approvals, "all_pending", lambda: [{"call_id": "c1", "conversation_id": "chat-tmp"},
                                                           {"call_id": "c2", "conversation_id": "chat-open"}])
    await _add(client, ConversationContext(id="chat-tmp", temporary=True, no_memory=True),
               ConversationContext(id="chat-off", no_memory=True), ConversationContext(id="chat-quick", kind="quick"))
    rows = []
    for cid in ("chat-tmp", "chat-off", "chat-quick", "chat-open"):
        rows += [*_chat(cid, f"SECRET opening of {cid}"), _run(cid, "recorded"), _job(f"j-{cid}", cid, "failed"),
                 _run(cid, "recording")]
    await _add(client, *rows)
    brief = await _tool()
    for key in ("done_today", "running", "stuck", "waiting_on_you"):
        assert _ids(brief[key]) == [("conversation", "chat-open")], key
        assert brief[key]["count"] == 1, key
    assert "SECRET opening of chat-open" in str(brief)
    assert "chat-tmp" not in str(brief) and "chat-off" not in str(brief) and "chat-quick" not in str(brief)
    # The badge is the user's own view, on the user's own screen: it still counts the temporary conversation's card.
    assert (await client.get("/api/v1/proactive/summary")).json()["waiting"]["count"] == 2


@pytest.mark.parametrize("own", [dict(temporary=True), dict(no_memory=True)])
async def test_inside_a_temporary_or_no_memory_conversation_it_refuses_as_conversation_search_does(client, own):
    from server.registry.executors import EXECUTORS
    from server.services import personal_context as pc
    await _add(client, *_chat("chat-open"), _run("chat-open", "recording"))
    ctx = pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="chat-here", model_is_local=True, **own)
    with pc.bind(ctx):
        got = await _tool()
        searched = await EXECUTORS["conversation_search"].execute({"query": "hello"})
    assert got == searched == {"ok": False, "external": False, "error": "memory is off for this conversation"}


async def test_a_cloud_model_with_memory_off_for_conversations_is_refused_as_conversation_search_is(client):
    from server.registry.executors import EXECUTORS
    from server.services import personal_context as pc
    await _add(client, *_chat("chat-open", "plan the trip"), _run("chat-open", "recording"))

    def ctx(**over):
        return pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="chat-here", **over)
    with pc.bind(ctx(model_is_local=False)):
        got = await _tool()
        searched = await EXECUTORS["conversation_search"].execute({"query": "plan"})
    assert got == searched and got["ok"] is False and "Settings" in got["error"]
    for allowed in (dict(model_is_local=True), dict(model_is_local=False, cloud_memory_default=True),
                    dict(model_is_local=False, cloud_memory_allowed=True)):
        with pc.bind(ctx(**allowed)):
            assert _ids((await _tool())["running"]) == [("conversation", "chat-open")], allowed


@pytest.mark.parametrize("key", ["done_today", "running", "stuck", "waiting_on_you"])
async def test_an_empty_install_has_nothing_in_any_line(client, monkeypatch, key):
    monkeypatch.setattr(approvals, "all_pending", lambda: [])
    brief = await _tool()
    assert brief[key] == {"count": 0, "items": [], "more": 0}
