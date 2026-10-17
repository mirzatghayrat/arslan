"""0.1.62 F1: a command runs for its own time limit, never past what the turn has left,
and a stop by any time limit still hands the model the output read so far."""
import asyncio
import os
import time
from pathlib import Path

import pytest

from arslan import execution_budget
from arslan.execution_budget import Budget, Limits
from server.orchestrator import tool_loop
from server.registry.executors import EXECUTORS
from server.services import terminal_exec

run = EXECUTORS["run_command"].execute


@pytest.fixture
def own_folder(execution_db):
    folder = Path(os.environ["ARSLAN_DEFAULT_WORKSPACE"])
    folder.mkdir(parents=True, exist_ok=True)       # terminal_exec.run is called directly below
    return folder


@pytest.fixture
def no_cards(monkeypatch):
    async def no():
        return False
    monkeypatch.setattr(tool_loop, "_asks_for_everything", no)
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", no)


async def _yes(command, argv, **kw):
    return True


async def _resolve():
    return [{"key": "run_command", "description": "run"}]


def _budget_with(remaining_s: float) -> Budget:
    """A turn budget with about `remaining_s` of wall time left."""
    return Budget(Limits(wall_seconds=remaining_s))


@pytest.fixture
def captured(monkeypatch):
    """terminal_exec.run replaced: records the time limit it was given, never runs anything."""
    calls: list[dict] = []

    async def fake_run(command, **kw):
        calls.append(kw)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(kw.get("cwd"))}
    monkeypatch.setattr(terminal_exec, "run", fake_run)
    return calls


# ── the limit follows the command's own argument ──────────────────────────────────────

async def test_a_long_command_outlives_the_tool_loops_default(own_folder, no_cards):
    # The loop's per-tool default (here 1 s, 20 s in the app) no longer cuts run_command.
    r = await tool_loop._dispatch_tool(
        "run_command", {"command": "sleep 2; echo done"}, "{}", resolve_tools=_resolve,
        emit=lambda e: None, tool_timeout_s=1, tool_trace=[], convo=[], confirm_command=_yes,
        conversation_id="c1")
    assert r["ok"] is True, r
    assert "done" in r["stdout"]


async def test_a_request_of_700_s_runs_as_600(own_folder, captured):
    assert terminal_exec.timeout_of(700) == 600
    with execution_budget.scope(_budget_with(3600)):
        await run({"command": "true", "timeout_s": 700})
    assert captured[-1]["timeout_s"] == 600


async def test_the_limit_never_outruns_the_turn(own_folder, captured):
    # 100 s left in the turn, 600 asked: 30 s stay for the model call that wraps up.
    with execution_budget.scope(_budget_with(100)):
        await run({"command": "true", "timeout_s": 600})
    assert 69 <= captured[-1]["timeout_s"] <= 70


async def test_without_time_left_the_command_never_starts(own_folder, captured):
    with execution_budget.scope(_budget_with(20)):
        r = await run({"command": "touch should-not-exist", "timeout_s": 600})
    assert captured == []
    assert r["ok"] is False and r["code"] == "time_limit" and r["executed"] is False


async def test_a_background_job_gets_the_same_rule(own_folder, captured):
    job = execution_budget.job_budget("standard")
    with execution_budget.scope(job):
        await run({"command": "true", "timeout_s": 600})
        assert captured[-1]["timeout_s"] == 600          # plenty left: the full 600
        job.started -= job.limits.wall_seconds - 100      # now 100 s left
        await run({"command": "true", "timeout_s": 600})
    assert 69 <= captured[-1]["timeout_s"] <= 70


# ── a stop by a time limit keeps the output ───────────────────────────────────────────

async def test_a_timeout_hands_over_the_output_read_so_far(own_folder):
    started = time.monotonic()
    r = await run({"command": "echo started; sleep 30", "timeout_s": 5})
    assert r["ok"] is False and r["code"] == "time_limit"
    assert r["error"] == "stopped after 5 s"            # M2 counts this exact text
    assert "started" in r["stdout"]
    assert time.monotonic() - started < 15


async def test_the_output_kept_in_memory_is_capped(own_folder):
    total = 20_000_000
    r = await terminal_exec.run(
        f"echo START; head -c {total} /dev/zero | tr '\\0' x; echo; echo END",
        cwd=own_folder, timeout_s=60)
    assert r["ok"] is True
    assert r["dropped_bytes"] >= total - terminal_exec.MAX_BUFFER_BYTES
    assert r["stdout"].startswith("START") and r["stdout"].rstrip().endswith("END")
    saved = Path(r["full_output_path"])
    assert saved.stat().st_size <= terminal_exec.MAX_BUFFER_BYTES + 4096


async def test_the_loops_backstop_says_it_was_the_time_limit(own_folder, no_cards, monkeypatch):
    class Stuck:
        key = "run_command"
        timeout_s = terminal_exec.MAX_TIMEOUT_S + 15

        async def execute(self, args):
            await asyncio.sleep(30)
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", Stuck())
    # 10.5 s left: the backstop is what is left minus 10 s, so it fires after ~0.5 s.
    with execution_budget.scope(_budget_with(10.5)):
        r = await tool_loop._dispatch_tool(
            "run_command", {"command": "ls"}, "{}", resolve_tools=_resolve, emit=lambda e: None,
            tool_timeout_s=20, tool_trace=[], convo=[], confirm_command=_yes, conversation_id="c1")
    assert r["ok"] is False and r["code"] == "time_limit"
    assert r["error"] == "stopped by the time limit; no output was captured"
