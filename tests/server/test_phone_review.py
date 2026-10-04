"""Quick review from the phone (mobile-bridge-protocol §5.3 run.result): what the Mac records of
each tool call, how a run reads back for a phone screen, each conversation's kind and state,
today's activity, and tasks started and stopped from the phone."""
import asyncio
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from server.db.models import ArslanMessage, Run
from server.services import (artifact_store, background_jobs, desktop_status, execution_context, phone_reads,
                             run_recorder, run_registry, tool_review)
from server.services.background_jobs import Job
from server.ws.arslan import _to_frame


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    desktop_status._reset_for_tests()
    background_jobs._jobs.clear()
    run_registry._recorders.clear()
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda run_id: None)
    yield
    desktop_status._reset_for_tests()
    background_jobs._jobs.clear()
    run_registry._recorders.clear()


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "artifacts")
    return tmp_path / "artifacts"


# ------------------------------------------------------------------ what is recorded

def test_an_edit_keeps_its_old_and_new_text_bounded():
    review = tool_review.capture("edit_file", {"path": "a.py", "old": "x = 1", "new": "x = 2" + "y" * 7000},
                                 {"ok": True, "path": "a.py"})
    assert review["kind"] == "edit" and review["path"] == "a.py" and review["old"] == "x = 1"
    assert len(review["new"]) <= tool_review.SNIPPET_CHARS + 2 and review["new"].endswith("…")


def test_a_command_keeps_its_line_exit_and_the_last_lines_without_colour_codes():
    output = "\n".join(f"line {i}" for i in range(100)) + "\n\x1b[32mPASS\x1b[0m"
    review = tool_review.capture("run_command", {"command": "npm", "argv": ["test", "--silent"]},
                                 {"ok": True, "stdout": output, "stderr": "warn: slow", "exit_code": 0})
    assert review["command"] == "npm test --silent" and review["exit"] == 0
    assert len(review["lines"]) == tool_review.TAIL_LINES
    assert review["lines"][-2:] == ["PASS", "warn: slow"]


def test_a_new_file_keeps_its_size_head_and_artifact():
    review = tool_review.capture("write_file", {"path": "r.md", "content": "# R\n" * 10},
                                 {"ok": True, "path": "r.md", "artifact": {"filename": "run_7_ab_r.md"}})
    assert (review["kind"], review["bytes"], review["file_id"]) == ("write", 40, "run_7_ab_r.md")
    assert tool_review.capture("web_search", {"query": "q"}, {"ok": True}) == {"kind": "search", "query": "q"}
    assert tool_review.capture("browser_open", {"url": "https://x.dev"}, {})["kind"] == "web"
    assert tool_review.capture("update_plan", {}, {}) is None


def test_review_and_target_never_reach_a_window():
    frame = _to_frame({"type": "tool_result", "tool": "edit_file", "ok": True, "summary": "ok",
                       "review": {"kind": "edit", "old": "secret", "new": "secret"}})
    assert "review" not in frame
    assert "target" not in _to_frame({"type": "tool_call", "tool": "run_command", "args_summary": "{}", "target": "npm"})


# ------------------------------------------------------------------ a change, for a phone screen

def test_a_change_reads_as_context_and_marked_lines():
    rows, added, removed = phone_reads.change_lines("def load(p):\n    a = 1\n    return a\n",
                                                    "def load(p):\n    a = 2\n    b = 3\n    return a\n")
    assert (added, removed) == (2, 1)
    assert rows == [[" ", 1, 1, "def load(p):"], ["-", 2, None, "    a = 1"], ["+", None, 2, "    a = 2"],
                    ["+", None, 3, "    b = 3"], [" ", 3, 4, "    return a"]]


def test_a_long_unchanged_stretch_folds_to_a_count():
    old = "\n".join(f"l{i}" for i in range(30))
    new = old.replace("l15", "L15")
    rows, added, removed = phone_reads.change_lines(old, new)
    assert (added, removed) == (1, 1)
    assert rows[0] == ["fold", None, None, "13"] and rows[-1] == [" ", 18, 18, "l17"]
    assert [r[0] for r in rows].count(" ") == 4, "two lines of context each side"


def test_a_step_without_review_still_has_a_kind():
    step = phone_reads.phone_step("web_extract", True, 830, {"target": "ctrip.com", "summary": "page read"})
    assert step == {"kind": "web", "tool": "web_extract", "ok": True, "ms": 830, "target": "ctrip.com", "summary": "page read"}


# ------------------------------------------------------------------ a run, end to end

async def test_a_finished_run_reads_back_with_terminal_diff_and_new_file(client, artifacts):
    rec = await run_recorder.RunRecorder.start(conversation_id="task-1", spawn_id=None, spawn_name="Arslan",
                                               user_message="把 Q3 销售数据做成一页报告", kind="host")
    tee = rec.tee(lambda e: None)
    with execution_context.bind_run(rec.run_id):
        artifact = artifact_store.store_bytes(rec.run_id, "report.md", b"# Q3\n")
    for tool, args, result, target in [
        ("run_command", {"command": "python make_report.py"}, {"ok": True, "stdout": "Loaded 1,204 rows\nPDF written", "exit_code": 0}, "python make_report.py"),
        ("edit_file", {"path": "make_report.py", "old": "df = read(p)\n", "new": "df = read(p, dates=True)\n"}, {"ok": True, "path": "make_report.py"}, "make_report.py"),
        ("write_file", {"path": "report.md", "content": "# Q3\n"}, {"ok": True, "path": "report.md", "artifact": artifact}, "report.md"),
    ]:
        tee({"type": "tool_call", "tool": tool, "args_summary": "{}", "target": target})
        tee({"type": "tool_result", "tool": tool, "ok": True, "summary": "ok", "review": tool_review.capture(tool, args, result)})
    await rec.finalize(summary_message_id=None, full_output="done")

    got = (await client.get(f"/api/v1/phone/runs/{rec.run_id}")).json()
    assert (got["state"], got["total"], got["title"]) == ("done", 3, "把 Q3 销售数据做成一页报告")
    command, edit, write = got["steps"]
    assert command["terminal"] == {"command": "python make_report.py", "exit": 0, "lines": ["Loaded 1,204 rows", "PDF written"]}
    assert (edit["diff"]["added"], edit["diff"]["removed"], edit["target"]) == (1, 1, "make_report.py")
    assert write["diff"]["new_file"] is True and write["file_id"] == artifact["filename"]
    assert [f["id"] for f in got["files"]] == [artifact["filename"]]
    assert (await client.get("/api/v1/phone/runs/999")).status_code == 404


async def test_a_run_still_in_flight_reads_from_its_recorder(client):
    rec = await run_recorder.RunRecorder.start(conversation_id="c", spawn_id=None, spawn_name="Arslan",
                                               user_message="检查死链接", kind="host")
    run_registry._recorders[rec.run_id] = rec
    tee = rec.tee(lambda e: None)
    tee({"type": "tool_call", "tool": "web_extract", "args_summary": "{}", "target": "aralem.dev"})
    tee({"type": "tool_result", "tool": "web_extract", "ok": True, "summary": "read", "review": {"kind": "web", "url": "https://aralem.dev"}})
    tee({"type": "tool_call", "tool": "web_extract", "args_summary": "{}", "target": "aralem.dev/notes"})
    got = (await client.get(f"/api/v1/phone/runs/{rec.run_id}")).json()
    assert got["state"] == "working"
    assert [s["target"] for s in got["steps"]] == ["aralem.dev", "aralem.dev/notes"]
    assert got["steps"][-1].get("running") is True and "running" not in got["steps"][0]


async def test_history_names_each_reply_s_run(client):
    async with client.db_maker() as db:
        db.add(Run(id=5, conversation_id="trip", user_message="plan"))
        db.add(ArslanMessage(id=1, conversation_id="trip", role="arslan", content="done", run_id=5))
        db.add(ArslanMessage(id=2, conversation_id="trip", role="user", content="thanks"))
        await db.commit()
    got = (await client.get("/api/v1/phone/conversations/trip/history")).json()["messages"]
    assert [m.get("run_id") for m in got] == [5, None]


# ------------------------------------------------------------------ kind and state

async def test_each_conversation_says_its_kind_state_and_origin(client, artifacts):
    async with client.db_maker() as db:
        db.add(Run(id=9, conversation_id="trip", user_message="x"))
        for i, (cid, role, source, text, run_id, outcome) in enumerate([
            ("pocket", "user", "phone", "在干嘛", None, None),
            ("task-ab", "user", "phone", "整理发票", None, None),
            ("task-ab", "arslan", None, "整理好了", None, "done"),
            ("scheduled-3", "arslan", None, "今日新闻", None, None),
            ("trip", "user", None, "规划行程", None, None),
            ("trip", "arslan", None, "行程排好了，见附件", 9, None),
            ("busy", "user", None, "跑测试", None, None),
            ("ask", "user", None, "删重复文件", None, None),
            ("task-no", "user", "phone", "复制文件", None, None),
            ("task-no", "arslan", None, "没做成", None, "blocked"),
            ("task-part", "arslan", None, "做了一半", None, "partial"),
        ], start=1):
            db.add(ArslanMessage(id=i, conversation_id=cid, role=role, source=source, content=text, run_id=run_id, job_outcome=outcome))
        await db.commit()
    artifact_store.store_bytes(9, "行程.md", b"# trip")
    # "answer-delivered" passing is not one of the job's own checks: 1 of 2, as its job.event says.
    background_jobs._jobs["j"] = Job("j", "busy", "跑测试", [{"id": "answer-delivered", "description": "x"}, {"id": "c1", "description": "y"},
                                                          {"id": "c2", "description": "z"}],
                                     phase="running", step="run_command npm test", results={"answer-delivered": "passed", "c1": "passed"})
    with desktop_status.awaiting_approval("ask"):
        rows = {c["id"]: c for c in (await client.get("/api/v1/phone/conversations?limit=50")).json()["conversations"]}
    assert (rows["pocket"]["kind"], rows["pocket"]["title"], rows["pocket"]["origin"]) == ("remote", "Remote", "phone")
    assert (rows["task-ab"]["kind"], rows["task-ab"]["state"], rows["task-ab"]["origin"]) == ("task", "done", "phone")
    assert rows["scheduled-3"]["kind"] == "scheduled"
    assert (rows["trip"]["kind"], rows["trip"]["files"], rows["trip"]["preview"]) == ("chat", 1, "行程排好了，见附件")
    assert rows["busy"]["state"] == "working" and rows["busy"]["job"] == {"id": "j", "step": "run_command npm test", "done": 1, "total": 2}
    assert rows["ask"]["state"] == "waiting"
    # Done only when it got done: partly or stuck is "unfinished" (the phone's yellow 没做成).
    assert (rows["task-no"]["state"], rows["task-part"]["state"]) == ("unfinished", "unfinished")


async def test_a_stopped_job_reads_failed_not_unfinished(client):
    async with client.db_maker() as db:
        db.add(ArslanMessage(conversation_id="task-stop", role="user", source="phone", content="等 150 秒"))
        await db.commit()
    background_jobs._jobs["s"] = Job("s", "task-stop", "等 150 秒", [{"id": "answer-delivered", "description": "x"}],
                                     phase="finished", outcome="stopped")
    try:
        rows = {c["id"]: c for c in (await client.get("/api/v1/phone/conversations?limit=50")).json()["conversations"]}
    finally:
        background_jobs._jobs.pop("s", None)
    assert rows["task-stop"]["state"] == "failed"


# ------------------------------------------------------------------ today's activity

async def test_today_is_counted_by_hour_and_kind(client, artifacts):
    now = datetime.now(UTC).replace(tzinfo=None)
    async with client.db_maker() as db:
        db.add(Run(id=1, conversation_id="a", user_message="x", started_at=now, status="recorded"))
        db.add(Run(id=2, conversation_id="b", user_message="y", started_at=now, status="recording"))
        db.add(Run(id=3, conversation_id="c", user_message="z", started_at=now, status="recorded", error_kind="HostError"))
        await db.commit()
    background_jobs._jobs["j"] = Job("j", "b", "task", [], run_id=2)
    desktop_status.push("approval_needed", conversation_id="a")
    artifact_store.store_bytes(1, "a.txt", b"x")
    async with client.db_maker() as db:
        got = await phone_reads.activity(db, now=time.time())
    hour = datetime.now().hour
    assert got["hours"][hour] == [2, 1, 1], "two chat turns, one task, one approval this hour"
    assert sum(sum(h) for h in got["hours"]) == 4
    assert (got["done"], got["files"], got["waiting"]) == (1, 1, 0)


# ------------------------------------------------------------------ tasks from the phone

async def test_a_task_from_the_phone_gets_its_own_conversation_and_a_job(client, monkeypatch):
    started = {}

    async def fake_start(cid, goal, criteria, *, origin="mac"):
        started.update(cid=cid, goal=goal, criteria=criteria, origin=origin)
        return SimpleNamespace(job_id="job-1")
    monkeypatch.setattr(background_jobs, "start", fake_start)
    got = (await client.post("/api/v1/phone/tasks", json={"goal": "  把发票整理成表  ", "criteria": ["每张一行", " ", "按月小计", "a", "b"]})).json()
    assert got["job_id"] == "job-1" and got["conversation_id"].startswith("task-")
    assert started == {"cid": got["conversation_id"], "goal": "把发票整理成表",
                       "criteria": [{"description": "每张一行"}, {"description": "按月小计"}, {"description": "a"}], "origin": "phone"}
    async with client.db_maker() as db:
        from sqlalchemy import select
        msg = (await db.execute(select(ArslanMessage).where(ArslanMessage.conversation_id == got["conversation_id"]))).scalar_one()
    assert (msg.role, msg.content, msg.source) == ("user", "把发票整理成表", "phone")
    assert (await client.post("/api/v1/phone/tasks", json={"goal": "   "})).status_code == 422


async def test_a_running_task_can_be_stopped_from_the_phone(client):
    task = asyncio.get_running_loop().create_future()
    background_jobs._jobs["j"] = Job("j", "task-x", "goal", [], phase="running", task=task)
    assert (await client.post("/api/v1/phone/tasks/j/stop")).json() == {"job_id": "j", "stopped": True}
    assert task.cancelled()
    assert (await client.post("/api/v1/phone/tasks/nope/stop")).status_code == 404


def test_a_job_says_what_it_is_doing_and_which_run_it_is():
    job = Job("j", "c", "goal", [])
    seen = []
    sink = background_jobs._job_sink(job, seen.append)
    with execution_context.bind_run(42):
        sink({"type": "tool_call", "tool": "run_command", "target": "npm test"})
    assert (job.step, job.run_id) == ("run_command npm test", 42)
    assert job.frame()["run_id"] == 42 and job.frame()["origin"] == "mac"
