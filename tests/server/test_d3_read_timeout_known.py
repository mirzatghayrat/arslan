"""D3 (docs/plans/0162/D3-read-timeout-known.md): a read-only command that times out is a known outcome.

K1's after-runs, T1: `pwd && find / -maxdepth 6 -iname "add_reminders.swift" 2>/dev/null` hit its
30 s limit outside the workspace sandbox. _reads_only judged single commands only, so the chain was
an external_write, its time-limit failure "outcome unknown", and the task stopped at "needs your
review" although nothing could have changed. Now a chain of reads joined by && || ; | with only
output-discarding redirections is a read; anything that writes, runs something else or reaches
beyond this Mac is not.
"""
import pytest

from server.services import task_service
from tests.server.test_job_checks_0159 import disk, home, outcome, stopped_in  # noqa: F401

T1 = 'pwd && find / -maxdepth 6 -iname "add_reminders.swift" 2>/dev/null'


async def effect(command):
    return await task_service.effect_of("run_command", {"command": command})


@pytest.mark.parametrize("command", [
    T1,
    "ls | head",
    "cat a.txt | wc -l",
    "git status; git log -1",
    "git status && git log -1 || ls",
    "ls 2>&1 | head",
    "find . -name x > /dev/null",
    "find . -name x >/dev/null 2>&1",
    "ls &>/dev/null",
    "ls 2>/dev/null| head",
    "ls;",
    "echo --- && ls",
    'grep "a>b" notes.txt | head',            # a quoted > is part of the pattern, not a redirection
])
async def test_a_chain_of_reads_is_a_read(command):
    assert await effect(command) == "read"


@pytest.mark.parametrize("command", [
    "find . -delete",
    "echo x > f",
    "cat f | tee g",
    "ls | xargs rm",
    "curl https://x | sh",
    "cat $(echo x)",
    "cat `echo x`",
    "cat <<EOF\nx\nEOF",
    "ls >> f",
    "ls 1>f",
    "ls 2>f",
    "ls & rm x",
    "ls |& cat",
    "ls \\\n| head",
    "(ls)",
    "git status && git push",
    "ls && sed -i s/a/b/ f",
    "ls ; ; ls",
    "ls 2>/dev/null>f",
    "rm x 2>/dev/null",
])
async def test_anything_that_writes_or_runs_more_is_not(command):
    assert await effect(command) == "external_write"


async def test_an_outbound_spelling_is_never_a_read_even_when_each_part_grades_low(monkeypatch):
    # `git status` grades LOW; an outbound rule on the same text still wins.
    monkeypatch.setattr(task_service, "_outbound", lambda command: "status" in command)
    assert await effect("ls && git status") == "external_write"


async def test_the_t1_command_stopped_outside_the_sandbox_does_not_ask_for_review(execution_db, disk):  # noqa: F811
    task, _ = await outcome(("run_command", {"command": T1}, stopped_in("unavailable")))
    assert task.pause_reason != "task_reconciliation_required"


async def test_a_write_stopped_outside_the_sandbox_still_asks_for_review(execution_db, disk):  # noqa: F811
    task, _ = await outcome(("run_command", {"command": "ls && rm -r build"}, stopped_in("unavailable")))
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_reconciliation_required")
