"""Leaving the sandbox is a click (0.1.51 P3): the tool loop's three ways out —
asked up front, offered after a stop, or granted for the rest of a conversation (a stored
grant since S4a: tests/server/test_s4a_outside_remote.py) — and the cards that carry them."""
import pytest

from server.orchestrator import tool_loop
from server.services import command_sandbox, terminal_exec


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    command_sandbox._reset_for_tests()

    async def no():
        return False

    async def yes():
        return True
    monkeypatch.setattr(tool_loop, "_asks_for_everything", no)
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", yes)
    # S2a-2 (R4): layer ③ runs with no card only where the sandbox can start; these tests are about
    # what happens after it starts, on every platform.
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    yield
    command_sandbox._reset_for_tests()


class _Exec:
    """Stand-in executor: 'stopped by the sandbox' unless the loop let it out."""
    key = "run_command"

    def __init__(self, stop=True):
        self.stop = stop
        self.outside: list[bool] = []

    async def execute(self, args):
        out = terminal_exec.OUTSIDE_SANDBOX.get()
        self.outside.append(out)
        if self.stop and not out:
            return {"ok": False, "exit_code": 1, "stdout": "", "stderr": "operation not permitted: /x",
                    "sandbox": "workspace", "sandbox_denied": True, "note": "stopped"}
        return {"ok": True, "exit_code": 0, "stdout": "done", "stderr": "", "sandbox": "off" if out else "workspace"}


class _Cards:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []

    async def __call__(self, command, argv, **kw):
        self.calls.append({"command": command, **kw})
        return self.answers.pop(0) if self.answers else False


async def _resolve():
    return [{"key": "run_command", "description": "run"}]


async def _dispatch(monkeypatch, args, *, executor, cards=None, cid="c1"):
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", executor)
    return await tool_loop._dispatch_tool(
        "run_command", args, "{}", resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5,
        tool_trace=[], convo=[], confirm_command=cards, conversation_id=cid)


async def test_a_stopped_command_is_offered_one_rerun_outside(monkeypatch):
    # S2a-2: layer ③ runs in the sandbox with no card (the tool loop decides that, once); a stop
    # offers the retry card.
    ex, cards = _Exec(), _Cards(True)
    r = await _dispatch(monkeypatch, {"command": "ls"}, executor=ex, cards=cards)
    assert ex.outside == [False, True]
    assert [c.get("sandbox") for c in cards.calls] == ["retry"]
    assert r["ok"] is True and r["ran_outside_sandbox"] is True


async def test_declining_the_rerun_leaves_it_stopped_with_the_note(monkeypatch):
    ex = _Exec()
    cards = _Cards()                              # every card: no

    async def ordinary_yes(command, argv, **kw):
        cards.calls.append({"command": command, **kw})
        return kw.get("sandbox") is None          # the ordinary card says yes, the retry no
    r = await _dispatch(monkeypatch, {"command": "ls"}, executor=ex, cards=ordinary_yes)
    assert ex.outside == [False]
    assert r["ok"] is False and r["sandbox_denied"] is True and "ran_outside_sandbox" not in r
    assert cards.calls[-1]["sandbox"] == "retry"


async def test_without_a_window_a_stop_is_final(monkeypatch):
    ex = _Exec()
    r = await _dispatch(monkeypatch, {"command": "ls"}, executor=ex, cards=None)
    assert ex.outside == [False] and r["sandbox_denied"] is True


async def test_asking_up_front_takes_one_card_that_covers_the_command_too(monkeypatch):
    ex, cards = _Exec(stop=False), _Cards(True)
    r = await _dispatch(monkeypatch, {"command": "rm old.dmg", "outside_sandbox": True,
                                      "why": "clean up Downloads"}, executor=ex, cards=cards)
    assert len(cards.calls) == 1                   # rm would card anyway: still ONE card
    assert cards.calls[0]["sandbox"] == "outside" and cards.calls[0]["why"] == "clean up Downloads"
    assert ex.outside == [True] and r["ran_outside_sandbox"] is True


async def test_asking_up_front_always_cards_even_a_harmless_command(monkeypatch):
    ex, cards = _Exec(stop=False), _Cards(False)
    r = await _dispatch(monkeypatch, {"command": "ls", "outside_sandbox": True}, executor=ex, cards=cards)
    assert cards.calls[0]["sandbox"] == "outside"
    assert ex.outside == [] and r["ok"] is False and "declined" in r["error"]


async def test_asking_up_front_without_a_window_is_refused(monkeypatch):
    ex = _Exec(stop=False)
    r = await _dispatch(monkeypatch, {"command": "ls", "outside_sandbox": True}, executor=ex, cards=None)
    assert ex.outside == [] and r["ok"] is False and "nobody to ask" in r["error"]  # S1 (U14 c): a scheduled run's refusal says what decide() says


async def test_a_conversation_grant_runs_outside_from_the_start_there_only(execution_db, monkeypatch):
    from server.db import session as db_session
    from server.services import permission_store, permissions
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, "c1", "", "outside", "*", call_id="card-1")
        await db.commit()

    async def no_card(frame):
        raise AssertionError("no card is shown")
    ex, cards = _Exec(), _Cards(True)
    with permissions.asking_with(no_card):
        r = await _dispatch(monkeypatch, {"command": "ls", "outside_sandbox": True}, executor=ex, cards=cards, cid="c1")
        assert ex.outside == [True] and r["ran_outside_sandbox"] is True
        assert all(c.get("sandbox") is None for c in cards.calls)       # no sandbox card
        other = _Exec()
        other_cards = _Cards(False)
        await _dispatch(monkeypatch, {"command": "ls"}, executor=other, cards=other_cards, cid="c2")
    assert other.outside == [False] and other_cards.calls[-1]["sandbox"] == "retry"


async def test_with_the_sandbox_switched_off_nothing_about_it_asks(monkeypatch):
    async def off():
        return False
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", off)
    ex, cards = _Exec(), _Cards(True)
    r = await _dispatch(monkeypatch, {"command": "ls", "outside_sandbox": True}, executor=ex, cards=cards)
    assert all(c.get("sandbox") is None for c in cards.calls)
    assert ex.outside == [False] and "ran_outside_sandbox" not in r


def test_the_card_frame_says_which_sandbox_question_it_is():
    from server.ws import protocol
    f = protocol.propose_run_command("id", "mv a b", [], reason="", sandbox="outside", why="w" * 400)
    assert f["sandbox"] == "outside" and len(f["why"]) == 300
    assert "sandbox" not in protocol.propose_run_command("id", "ls", [])
    assert "sandbox" not in protocol.propose_run_command("id", "ls", [], sandbox="sideways")


def _window(frames: list, approve: bool):
    """Every window on the conversation, played by the test: it keeps each card a job shows and
    answers it (0.1.61: a job's cards are its BroadcastAsker's, not `approvals.ask`)."""
    from server.services import approvals

    def window(frame):
        if frame["type"].startswith("propose_"):
            frames.append(frame)
            approvals.answer({"type": ("confirm_" if approve else "cancel_") + frame["type"].removeprefix("propose_"),
                              "call_id": frame["call_id"], "remember": True})
    return window


async def test_a_background_job_asks_with_a_card_and_a_bare_yes_grants_nothing(execution_db, monkeypatch):
    """A yes that names no scope (an old client's "remember") is the card's first choice, this time."""
    from server.services import approvals, run_registry
    frames = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: _window(frames, True))
    job = approvals.JobConfirmations("c9")
    assert await job.command("mv a ~/b", [], sandbox="retry") is True
    assert frames[0]["sandbox"] == "retry" and frames[0]["options"] == ["once", "conversation"]
    from sqlalchemy import select
    from server.db.models import PermissionGrant
    async with execution_db() as db:
        assert (await db.execute(select(PermissionGrant))).scalars().all() == []
