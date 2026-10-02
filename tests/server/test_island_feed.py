"""Island feed (0.1.51 I1): work in flight with its latest step and plan, cards
waiting, recent events with title and summary — and the status endpoint that
notifications read stays contentless."""
import asyncio

import pytest

from server.services import desktop_status
from tests.server.test_scheduler import memdb  # noqa: F401 — fixture import


@pytest.fixture(autouse=True)
def fresh():
    desktop_status._reset_for_tests()
    yield
    desktop_status._reset_for_tests()


def test_work_in_flight_shows_with_title_kind_step_and_plan():
    with desktop_status.working("c1", title="找 10 个上海产品经理岗位\n，存成表格", kind="job"):
        desktop_status.note_step("web_extract", {"url": "https://www.careers.example.com/job/1?x=y"})
        desktop_status.note_plan([{"text": "find postings", "status": "done"},
                                  {"text": "collect 6/10  " + "z" * 80, "status": "in_progress"},
                                  {"text": "save", "status": "pending"}])
        active = desktop_status.island_feed()["active"]
        assert len(active) == 1
        a = active[0]
        assert a["kind"] == "job" and a["conversation_id"] == "c1"
        assert a["title"] == "找 10 个上海产品经理岗位 ，存成表格"          # one line
        assert a["step"]["tool"] == "web_extract" and a["step"]["target"] == "careers.example.com"
        assert a["plan"]["done"] == 1 and a["plan"]["total"] == 3
        assert [i["status"] for i in a["plan"]["items"]] == ["done", "in_progress", "pending"]
        assert len(a["plan"]["items"][1]["text"]) == desktop_status.PLAN_ITEM_CHARS
    assert desktop_status.island_feed()["active"] == []


def test_step_targets_are_short_and_never_full_arguments():
    t = desktop_status.step_target
    assert t("browser_open", {"url": "http://jobs.example.com/a/b"}) == "jobs.example.com"
    assert t("write_file", {"path": "reports/2026/jobs.csv", "content": "SECRET ROWS"}) == "jobs.csv"
    long = "x" * 80
    assert t("web_search", {"query": long}) == "x" * 39 + "…"
    assert t("run_command", {"command": "curl -s https://api.example.com/" + long}).endswith("…")
    assert t("remember", {"text": "private note"}) is None
    with desktop_status.working("c1"):
        desktop_status.note_step("write_file", {"path": "jobs.csv", "content": "SECRET ROWS"})
        assert "SECRET" not in str(desktop_status.island_feed())


def test_steps_outside_a_run_are_ignored():
    desktop_status.note_step("web_search", {"query": "q"})
    desktop_status.note_plan([{"text": "x", "status": "pending"}])
    assert desktop_status.island_feed()["active"] == []


def test_titles_and_summaries_reach_the_island_but_never_the_status_endpoint():
    desktop_status.push("turn_finished", conversation_id="c1", outcome="ok",
                        title="Find jobs", summary="Saved jobs.csv with 10 rows")
    feed = desktop_status.island_feed()["events"][0]
    assert feed["title"] == "Find jobs" and feed["summary"] == "Saved jobs.csv with 10 rows"
    status = desktop_status.snapshot()["events"][0]
    assert "title" not in status and "summary" not in status
    assert set(status) == {"id", "kind", "conversation_id", "outcome", "task_id", "at"}


def test_finished_events_say_which_kind_of_run_ended():
    desktop_status.push("turn_finished", conversation_id="c1", outcome="ok", work="job")
    desktop_status.push("turn_finished", conversation_id="c2", outcome="ok")
    first, second = desktop_status.island_feed()["events"]
    assert first["work"] == "job" and second["work"] is None
    assert "work" not in desktop_status.snapshot()["events"][0]
    with pytest.raises(ValueError):
        desktop_status.push("turn_finished", outcome="ok", work="chatter")


def test_details_leave_with_their_events():
    for i in range(desktop_status.MAX_EVENTS + 5):
        desktop_status.push("turn_finished", outcome="ok", title=f"t{i}")
    assert len(desktop_status._details) == desktop_status.MAX_EVENTS
    assert min(desktop_status._details) == desktop_status.snapshot()["events"][0]["id"]


def test_unknown_kind_of_work_is_refused():
    with pytest.raises(ValueError):
        with desktop_status.working("c1", kind="chatter"):
            pass


async def test_concurrent_runs_keep_their_own_steps():
    both_stepped, read = asyncio.Barrier(2), asyncio.Barrier(2)

    async def run(cid, query):
        with desktop_status.working(cid, title=cid):
            await asyncio.sleep(0)
            desktop_status.note_step("web_search", {"query": query})
            await both_stepped.wait()
            seen = {a["conversation_id"]: a["step"]["target"] for a in desktop_status.island_feed()["active"]}
            await read.wait()
            return seen
    a, b = await asyncio.gather(run("c1", "alpha"), run("c2", "beta"))
    assert a == b == {"c1": "alpha", "c2": "beta"}


def test_waiting_cards_name_their_conversations():
    with desktop_status.awaiting_approval("c9"):
        feed = desktop_status.island_feed()
        assert feed["awaiting"] == 1 and feed["awaiting_conversations"] == ["c9"]


async def test_feed_endpoint_and_setting(client):
    desktop_status.push("turn_finished", conversation_id="c1", outcome="ok", title="Find jobs")
    body = (await client.get("/api/v1/island/feed")).json()
    assert body["enabled"] is True and body["events"][0]["title"] == "Find jobs"
    r = await client.put("/api/v1/settings", json={"island_enabled": False})
    assert r.status_code == 200, r.text
    body = (await client.get(f"/api/v1/island/feed?after={body['cursor']}")).json()
    assert body["enabled"] is False and body["events"] == []
    settings = (await client.get("/api/v1/settings")).json()
    assert settings["island_enabled"] is False


async def test_the_tool_loop_reports_steps_and_plans(monkeypatch):
    from server.orchestrator import tool_loop
    from tests.server import test_trajectory_golden as golden
    seen = []

    class Rec(golden._Recorder):
        async def chat(self, *a, **k):
            seen.append([dict(x) for x in desktop_status.island_feed()["active"]])
            return await super().chat(*a, **k)
    adapter = Rec([golden._Resp(None, [golden._tc("update_plan", {"items": [{"text": "find", "status": "done"},
                                                                       {"text": "save", "status": "pending"}]}, "p1"),
                                       golden._tc("web_search", {"query": "jobs in shanghai"}, "s1")]),
                   golden._Resp("done")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", golden._Search())

    async def resolve():
        return [{"key": "web_search", "description": "s"}, {"key": "update_plan", "description": "p"}]
    with desktop_status.working("c1", title="jobs"):
        await tool_loop.run_native(system="S", user_content="jobs", history=[], emit=lambda e: None,
                                   on_chunk=lambda c: None, resolve_tools=resolve)
    last = seen[-1][0]
    assert last["step"]["tool"] == "web_search" and last["step"]["target"] == "jobs in shanghai"
    assert last["plan"]["done"] == 1 and last["plan"]["total"] == 2
