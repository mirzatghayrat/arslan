"""0.1.59: a background job that did the work counts as done; no ghost reply after a reconnect.

Seen recording the promo on v0.1.59-beta.2 (docs/specs/2026-10-10-0159-job-checks.md):
- nine invoices copied into ~/ArslanDemo/Invoices, answer right — "Stuck": file_saved only matched
  files Arslan produced, and two failed heredoc commands made the job "needs your review" for good;
- the design notes read, answer excellent — "Partly done": sources_read counted only web pages;
- after a finished answer a frozen half copy and a running timer: an answered run was replayed.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import time
from pathlib import Path

import pytest

from arslan.companion.contracts import AcceptanceCheck, TaskSpec
from server.services import background_jobs, file_reader, run_registry, settings_service, task_service, task_validation
from server.services.task_repository import repository


def check(kind, id="expected", **rule):
    return AcceptanceCheck.model_validate({"id": id, "description": "Check fixture",
                                           "evaluator": "deterministic", "rule": {"kind": kind, **rule}})


def copy(trace_command: str) -> dict:
    return {"tool": "run_command", "args": {"command": trace_command}, "result": {"ok": True, "exit_code": 0}}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A readable folder standing in for the user's home; one unreadable folder beside it."""
    readable = tmp_path / "home"
    (readable / "Downloads").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    return readable


def ctx(home: Path, since: float | None = None) -> dict:
    return {"roots": [home.resolve()], "workspace": home.resolve(), "since": since if since is not None else time.time() - 60}


# --- A1: file_saved looks at the disk ------------------------------------------------------------

def test_a_folder_the_user_named_passes_once_the_files_are_in_it(home):
    invoices = home / "Invoices"
    invoices.mkdir()
    for month in ("01", "02", "04"):
        (invoices / f"invoice-2026-{month}.pdf").write_bytes(b"%PDF fixture")
    trace = [copy(f"mkdir -p '{invoices}' && cp {home}/Downloads/invoice-2026-*.pdf {invoices}/")]
    result = task_validation.evaluate(check("file_saved", target="Invoices", minimum=3), "Done", [], trace, ctx(home))
    assert (result["status"], result["code"]) == ("passed", "file_saved_assertion")
    # The old rule — what file_saved used to become — can never pass here (the reported bug).
    assert task_validation.evaluate(check("artifact", target="Invoices"), "Done", [], trace, ctx(home))["status"] == "failed"


def test_too_few_new_files_or_an_untouched_folder_do_not_pass(home):
    invoices = home / "Invoices"
    invoices.mkdir()
    (invoices / "old.pdf").write_bytes(b"%PDF")
    trace = [copy(f"cp a.pdf {invoices}/")]
    assert task_validation.evaluate(check("file_saved", target="Invoices", minimum=2), "", [], trace,
                                    ctx(home))["status"] == "failed"
    # Everything in it predates the task (the task "started" a minute from now).
    late = ctx(home, since=time.time() + 60)
    result = task_validation.evaluate(check("file_saved", target="Invoices"), "", [], trace, late)
    assert (result["status"], result["code"]) == ("failed", "file_unchanged")


def test_a_quoted_folder_with_spaces_in_a_command_is_found(home):
    garden = home / "Pocket Garden" / "Sketches"
    garden.mkdir(parents=True)
    (garden / "a.png").write_bytes(b"png")
    trace = [copy(f'cp ~/x.png "{garden}/a.png"')]
    assert task_validation.evaluate(check("file_saved", target="Sketches"), "", [], trace, ctx(home))["status"] == "passed"


def test_a_saved_file_counts_and_an_empty_one_does_not(home):
    (home / "summary.md").write_text("# Summary\n")
    (home / "empty.md").write_text("")
    assert task_validation.evaluate(check("file_saved", target="summary.md"), "", [], [], ctx(home))["status"] == "passed"
    assert task_validation.evaluate(check("file_saved", target="empty.md"), "", [], [], ctx(home))["status"] == "failed"


def test_a_full_path_that_is_missing_fails_and_a_name_found_nowhere_is_not_run(home):
    missing = task_validation.evaluate(check("file_saved", target=str(home / "Invoices")), "", [], [], ctx(home))
    assert (missing["status"], missing["code"]) == ("failed", "file_missing")
    nowhere = task_validation.evaluate(check("file_saved", target="Invoices"), "", [], [], ctx(home))
    assert (nowhere["status"], nowhere["code"]) == ("not_run", "file_target_unresolved")


def test_nothing_outside_the_readable_folders_is_looked_at(home, monkeypatch):
    outside = home.parent / "elsewhere" / "Invoices"
    outside.mkdir()
    (outside / "a.pdf").write_bytes(b"%PDF")
    looked: list[str] = []
    real_scandir = os.scandir
    monkeypatch.setattr(task_validation.os, "scandir", lambda p: (looked.append(str(p)), real_scandir(p))[1])
    result = task_validation.evaluate(check("file_saved", target=str(outside)), "", [], [copy(f"cp a {outside}/")], ctx(home))
    assert (result["status"], result["code"]) == ("not_run", "file_target_unresolved")
    assert looked == []
    # Hidden and credential-shaped names inside the readable folder are refused the same way.
    (home / ".secret").mkdir()
    (home / ".secret" / "x").write_text("x")
    assert task_validation.evaluate(check("file_saved", target=str(home / ".secret")), "", [], [],
                                    ctx(home))["status"] == "not_run"


def test_without_disk_context_nothing_is_looked_at(home):
    (home / "summary.md").write_text("# Summary\n")
    assert task_validation.evaluate(check("file_saved", target=str(home / "summary.md")), "", [], [])["status"] == "not_run"


def test_a_verified_file_arslan_produced_still_counts(home):
    artifact = {"id": "a1", "filename": "run_9_x_report.md", "title": "Reports/report.md", "status": "passed"}
    assert task_validation.evaluate(check("file_saved", target="report.md"), "", [artifact], [], ctx(home))["status"] == "passed"
    bad = {**artifact, "status": "failed"}
    assert task_validation.evaluate(check("file_saved", target="report.md"), "", [bad], [], ctx(home))["status"] == "failed"


# --- B: sources_read counts local files read ------------------------------------------------------

READ_NOTES = {"tool": "read_file", "args": {"path": "Pocket Garden/design-notes.md"},
              "result": {"ok": True, "path": "~/ArslanDemo/Pocket Garden/design-notes.md", "content": "notes"}}


def test_reading_the_notes_counts_as_a_source():
    assert task_validation.evaluate(check("sources_read", minimum=1), "", [], [READ_NOTES])["status"] == "passed"
    assert task_validation.evaluate(check("sources_read", minimum=1, target="design-notes"), "", [], [READ_NOTES])["status"] == "passed"
    assert task_validation.evaluate(check("sources_read", minimum=1, target="budget"), "", [], [READ_NOTES])["status"] == "failed"
    assert task_validation.evaluate(check("sources_read", minimum=2), "", [], [READ_NOTES])["status"] == "failed"
    failed_read = {**READ_NOTES, "result": {"ok": False, "error": "file not found"}}
    assert task_validation.evaluate(check("sources_read", minimum=1), "", [], [failed_read])["status"] == "failed"
    # research_sources (research tasks) stays web-only — the rule sources_read used to become.
    assert task_validation.evaluate(check("research_sources", minimum=1), "", [], [READ_NOTES])["status"] == "failed"


def test_job_criteria_become_the_new_rules_and_round_trip():
    checks = background_jobs.criteria_to_acceptance([
        {"description": "Invoices copied", "kind": "file_saved", "target": "~/ArslanDemo/Invoices", "minimum": 9},
        {"description": "Notes read", "kind": "sources_read", "target": "design-notes.md"},
        {"description": "Three sources", "kind": "sources_read", "minimum": 3}])
    assert checks[1]["rule"] == {"kind": "file_saved", "target": "~/ArslanDemo/Invoices", "minimum": 9}
    assert checks[2]["rule"] == {"kind": "sources_read", "minimum": 1, "target": "design-notes.md"}
    assert checks[3]["rule"] == {"kind": "sources_read", "minimum": 3}
    for item in checks:                                       # every rule is a valid contract
        AcceptanceCheck.model_validate(item)
    again = background_jobs.criteria_from_acceptance(checks)
    assert again == [{"description": "Invoices copied", "kind": "file_saved", "target": "~/ArslanDemo/Invoices", "minimum": 9},
                     {"description": "Notes read", "kind": "sources_read", "minimum": 1, "target": "design-notes.md"},
                     {"description": "Three sources", "kind": "sources_read", "minimum": 3}]
    # A job started before 0.1.59 keeps its stored rule and continues with the same criterion.
    old = background_jobs.criteria_from_acceptance([{"id": "c", "description": "Saved", "rule": {"kind": "artifact", "target": "a.md"}}])
    assert old == [{"description": "Saved", "kind": "file_saved", "target": "a.md"}]


# --- A2 + the finish-time check, through the task runtime -----------------------------------------

async def run_contract(checks, body):
    spec = TaskSpec.model_validate({"id": "job-checks", "instruction": "Check fixture", "locale": "en",
        "scope": {"kind": "task", "owner_id": "local", "task_id": "job-checks"},
        "acceptance": [item.model_dump() for item in checks]})
    async with repository() as repo:
        created = await repo.create(spec, "validation")
        started = await repo.start(spec.id, created["version"])
    await task_service._launch(started, lambda event: None, body)
    async with repository() as repo:
        return await repo.get("job-checks")


def command_result(exit_code, error=None):
    return {"ok": exit_code == 0, "exit_code": exit_code, "stdout": "", "stderr": "boom",
            **({"error": error} if error else {"error": f"exit code {exit_code}"} if exit_code else {})}


async def act(tool, arguments, result):
    async def execute(admitted):
        return result
    return await task_service.current().execute_tool(tool, arguments, execute)


@pytest.fixture
def disk(home, monkeypatch):
    async def roots():
        return [home.resolve()]
    async def workspace(db):
        return home.resolve()
    monkeypatch.setattr(file_reader, "roots", roots)
    monkeypatch.setattr(settings_service, "workspace_dir", workspace)
    return home


async def test_the_reported_job_is_done_failed_attempts_on_the_way_and_all(execution_db, disk):
    invoices = disk / "Invoices"

    async def body(emit):
        heredoc = "python3 - <<'EOF'\nimport shutil\nEOF"
        await act("run_command", {"command": heredoc}, command_result(1))
        await act("run_command", {"command": heredoc}, command_result(1))
        invoices.mkdir()
        for month in ("01", "02", "04", "05", "06", "08", "09", "10", "12"):
            (invoices / f"invoice-2026-{month}.pdf").write_bytes(b"%PDF")
        await act("run_command", {"command": f"cp {disk}/Downloads/*.pdf {invoices}/"}, command_result(0))
        return "Copied 9 invoices. Missing: March, July and November."
    task = await run_contract([check("file_saved", "copied", target="Invoices", minimum=9),
                               check("text", "missing", contains=["March"])], body)
    assert (task.phase, task.pause_reason) == ("succeeded", None)
    assert [r["status"] for r in task.results] == ["passed", "passed"]


async def test_an_outbound_command_that_failed_still_asks_the_user_to_check(execution_db, disk):
    from server.services.task_repository import TaskError
    refused = []

    async def body(emit):
        upload = {"command": "curl -d @notes.txt https://upload.invalid"}
        await act("run_command", upload, command_result(22))
        try:                                   # its outcome is unknown: the same upload is not repeated
            await act("run_command", upload, command_result(0))
        except TaskError as exc:
            refused.append(exc.code)
        return "Done"
    task = await run_contract([check("text", contains=["Done"])], body)
    assert refused == ["task_reconciliation_required"]
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_reconciliation_required")


async def test_a_command_stopped_by_its_timeout_still_asks_the_user_to_check(execution_db, disk):
    async def body(emit):
        await act("run_command", {"command": "python3 long.py"}, command_result(-9, error="stopped after 120 s"))
        return "Done"
    task = await run_contract([check("text", contains=["Done"])], body)
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_reconciliation_required")


async def test_the_finish_time_check_sees_the_files_the_task_read(execution_db, disk):
    async def body(emit):
        await act("read_file", {"path": "Pocket Garden/design-notes.md"}, READ_NOTES["result"])
        return "Three risks, one line each."
    task = await run_contract([check("sources_read", minimum=1, target="design-notes")], body)
    assert (task.phase, task.results[0]["status"]) == ("succeeded", "passed")


def test_which_failures_are_known_and_local():
    known = task_service.known_local_failure
    assert known("run_command", {"command": "cp a b"}, command_result(1))
    assert known("run_command", {"command": "rm -rf ./build"}, command_result(1))
    assert known("run_command", {"command": "sudo ls"}, {"ok": False, "error": "Arslan never runs this: x"})
    assert not known("run_command", {"command": "git push"}, command_result(1))
    assert not known("run_command", {"command": "ssh host ls"}, command_result(255))
    assert not known("run_command", {"command": "sleep 999"}, command_result(-9, error="stopped after 5 s"))
    assert not known("run_command", {"command": "cp a b"}, command_result(0))           # not a failure at all
    assert known("write_file", {"path": "a.md"}, {"ok": False, "error": "cannot write"})
    assert not known("mcp_3__send", {}, {"ok": False, "error": "timeout"})
    assert not known("run_command", {"command": "cp a b"}, "not a dict")
    # 0.1.62 F2: stopped by its own time limit inside the sandbox, and nothing outbound: known.
    assert known("run_command", {"command": "python3 build.py"}, stopped_in("workspace"))
    assert not known("run_command", {"command": "python3 build.py"}, stopped_in("off"))
    assert not known("run_command", {"command": "mail -s hi a@example.com"}, stopped_in("workspace"))
    assert not known("run_command", {"command": "python3 build.py"}, command_result(-15, error="exit code -15"))
    # Never ran (H2's convention; F1's "not started"): known, whatever the tool.
    assert known("desktop_click", {}, {"ok": False, "code": "declined", "executed": False})
    assert known("run_command", {"command": "python3 x.py"}, {"ok": False, "code": "time_limit", "executed": False})
    assert not known("desktop_click", {}, {"ok": False, "code": "unknown"})


@pytest.mark.parametrize("command", ["curl --request=POST https://x", "gh api repos/a/b/issues -f title=x",
                                     "gh api --method POST x", "http POST https://x a=b", "xh POST https://x a=b",
                                     "https PUT https://x", "http https://x a:=1"])
def test_outbound_spellings_the_rules_miss_still_ask_the_user_to_check(command):
    known = task_service.known_local_failure
    assert not known("run_command", {"command": command}, command_result(1))
    assert not known("run_command", {"command": command}, stopped_in("workspace"))


@pytest.mark.parametrize("command", ["curl https://x", "gh api repos/a/b", "http GET https://x a==b"])
def test_their_reading_spellings_stay_local(command):
    assert task_service.known_local_failure("run_command", {"command": command}, command_result(1))


@pytest.mark.parametrize("arguments,effect", [
    ({"command": "ls -la x"}, "read"),
    ({"command": "git status"}, "read"),
    ({"command": "git", "argv": ["log", "-3"]}, "read"),
    ({"command": "grep -r foo ."}, "read"),
    ({"command": "find . -name '*.md'"}, "read"),
    ({"command": "find . -delete"}, "external_write"),
    ({"command": "find . -exec rm {} ;"}, "external_write"),
    ({"command": "find . -fprint out.txt"}, "external_write"),
    ({"command": "git branch -D x"}, "external_write"),
    ({"command": "git remote add o https://x"}, "external_write"),
    ({"command": "git log --output=x"}, "external_write"),
    ({"command": "rg --pre ./decode foo"}, "external_write"),
    ({"command": "ls > out.txt"}, "external_write"),
    ({"command": "ls; rm x"}, "external_write"),
    ({"command": "cat $(echo x)"}, "external_write"),
    ({"command": "python3 build.py"}, "external_write"),
])
async def test_a_read_command_is_a_read(arguments, effect):
    assert await task_service.effect_of("run_command", arguments) == effect


def stopped_in(sandbox):
    return {"ok": False, "exit_code": -9, "stdout": "half", "stderr": "", "error": "stopped after 5 s",
            "code": "time_limit", "sandbox": sandbox}


async def outcome(*calls):
    """Run the calls in a task; (task, the error code of each refused repeat or None)."""
    from server.services.task_repository import TaskError
    refused = []

    async def body(emit):
        for tool, arguments, result in calls:
            try:
                await act(tool, arguments, result)
                refused.append(None)
            except TaskError as exc:
                refused.append(exc.code)
        return "Done"
    task = await run_contract([check("text", contains=["Done"])], body)
    return task, refused


async def test_a_read_stopped_by_its_time_limit_does_not_ask_the_user_to_check(execution_db, disk):
    task, _ = await outcome(("run_command", {"command": "grep -r foo ."}, stopped_in("workspace")))
    assert task.pause_reason != "task_reconciliation_required"


async def test_a_read_killed_by_a_signal_does_not_ask_the_user_to_check(execution_db, disk):
    task, _ = await outcome(("run_command", {"command": "ls -la x"}, command_result(-15, error="exit code -15")))
    assert task.pause_reason != "task_reconciliation_required"


async def test_a_hands_action_that_never_ran_does_not_ask_the_user_to_check(execution_db, disk):
    task, _ = await outcome(("desktop_click", {"ref": "e1"}, {"ok": False, "code": "declined", "executed": False}))
    assert task.pause_reason != "task_reconciliation_required"


async def test_a_declined_command_card_does_not_ask_the_user_to_check(execution_db, disk):
    # Regression guard: a refused card returns before the task runtime records anything.
    from server.orchestrator import tool_loop

    async def no(command, argv, **kw):
        return False

    async def tools():
        return [{"key": "run_command", "description": "run"}]

    async def body(emit):
        await tool_loop._dispatch_tool("run_command", {"command": "git push"}, "{}", resolve_tools=tools,
                                       emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                                       confirm_command=no, conversation_id="f2")
        return "Done"
    task = await run_contract([check("text", contains=["Done"])], body)
    assert task.pause_reason != "task_reconciliation_required"


@pytest.mark.parametrize("arguments,result", [
    ({"command": "mail -s hi a@example.com"}, stopped_in("workspace")),
    ({"command": "python3 build.py"}, command_result(-15, error="exit code -15")),
    ({"command": "python3 build.py"}, stopped_in("off")),
    ({"command": "curl --request=POST https://x"}, command_result(22)),
    ({"command": "gh api --method POST x"}, stopped_in("workspace")),
])
async def test_what_may_have_happened_still_asks_the_user_to_check(execution_db, disk, arguments, result):
    task, _ = await outcome(("run_command", arguments, result))
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_reconciliation_required")


async def test_a_read_that_succeeded_can_run_again(execution_db, disk):
    _, refused = await outcome(*[("run_command", {"command": "ls -la x"}, command_result(0))] * 2)
    assert refused == [None, None]


async def test_a_known_failure_can_run_again(execution_db, disk):
    build = {"command": "python3 build.py"}
    _, refused = await outcome(("run_command", build, stopped_in("workspace")), ("run_command", build, command_result(0)))
    assert refused == [None, None]


@pytest.mark.parametrize("first", [command_result(-15, error="exit code -15"), stopped_in("off")])
async def test_an_unknown_outcome_is_not_repeated(execution_db, disk, first):
    build = {"command": "python3 build.py"}
    _, refused = await outcome(("run_command", build, first), ("run_command", build, command_result(0)))
    assert refused == [None, "task_reconciliation_required"]


# 0.1.62 F2 ④: a saved deliverable whose file check passed is not held by a work limit.

async def test_a_saved_and_checked_deliverable_finishes_despite_a_work_limit(execution_db, disk):
    async def body(emit):
        (disk / "report.md").write_text("# Report")
        await act("write_file", {"path": "report.md"}, {"ok": True, "path": "report.md"})
        task_service.current().limit_reason = "task_no_progress"
        return "Saved report.md"
    task = await run_contract([check("file_saved", "saved", target="report.md")], body)
    assert (task.phase, task.pause_reason) == ("succeeded", None)


@pytest.mark.parametrize("checks", [[check("file_saved", "saved", target="missing.md")],
                                    [check("text", contains=["Saved"])]])
async def test_without_a_passing_file_check_the_limit_still_holds(execution_db, disk, checks):
    async def body(emit):
        (disk / "report.md").write_text("# Report")
        await act("write_file", {"path": "report.md"}, {"ok": True, "path": "report.md"})
        task_service.current().limit_reason = "task_no_progress"
        return "Saved report.md"
    task = await run_contract(checks, body)
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_no_progress")


class _Runtime:
    pause_reason = None
    limit_reason = None


def test_the_loop_holds_a_limit_only_once_something_was_saved():
    from server.orchestrator import tool_loop
    saved, unsaved = _Runtime(), _Runtime()
    tool_loop._stop_for_limit(saved, "task_no_progress",
                              [{"tool": "write_file", "result": {"ok": True}}, {"tool": "web_search", "result": {}}])
    tool_loop._stop_for_limit(unsaved, "task_no_progress", [{"tool": "write_file", "result": {"ok": False}}])
    assert (saved.pause_reason, saved.limit_reason) == (None, "task_no_progress")
    assert (unsaved.pause_reason, unsaved.limit_reason) == ("task_no_progress", None)


# --- C: an answered run is not replayed --------------------------------------------------------

class _Recorder:
    def __init__(self, events):
        self._events = [(dt.datetime.utcnow(), ev) for ev in events]


async def test_a_run_whose_answer_ended_is_not_replayed_on_reconnect():
    async def work():
        await asyncio.sleep(30)
    answered, streaming = asyncio.create_task(work()), asyncio.create_task(work())
    try:
        run_registry.register(14, "ghost", answered, recorder=_Recorder([
            {"type": "stream_start", "run_id": 14}, {"type": "stream_chunk", "content": "Here's your memo"},
            {"type": "stream_end", "message_id": 15}]))
        run_registry.register(16, "ghost", streaming, recorder=_Recorder([
            {"type": "stream_start", "run_id": 16}, {"type": "stream_chunk", "content": "Working on"}]))
        assert [run_id for run_id, _ in run_registry.journal_snapshots("ghost")] == [16]
    finally:
        for run_id, task in ((14, answered), (16, streaming)):
            run_registry.unregister(run_id, "ghost")
            task.cancel()
