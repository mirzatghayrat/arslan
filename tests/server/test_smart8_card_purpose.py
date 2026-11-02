"""SMART-8 (the card mock the user OK'd, 2026-11-02): a confirm card leads with what the step is for. The model's own
reason for a command (`run_command`'s `why`) reached only the outside-sandbox and network cards; every command card now
carries it, cleaned as a name is (UNI1), so the card can show it as Arslan's words. What the step touches and its risk
are read by code on the card, never from this text."""
import pytest

from server.orchestrator import tool_loop
from server.services import command_confirm, command_sandbox, permissions
from server.ws import protocol


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    command_sandbox._reset_for_tests()

    async def no():
        return False

    async def yes():
        return True
    monkeypatch.setattr(tool_loop, "_asks_for_everything", no)
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", yes)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    yield
    command_sandbox._reset_for_tests()


class _Exec:
    key = "run_command"

    async def execute(self, args):
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}


class _Cards:
    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, command, argv, **kw):
        self.calls.append({"command": command, **kw})
        return False


class _Asker:
    def __init__(self):
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": False, "scope": "once", "note": "", "by": "mac", "call_id": frame["call_id"]}


async def _resolve():
    return [{"key": "run_command", "description": "run"}]


async def _dispatch(monkeypatch, args, cards):
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", _Exec())
    return await tool_loop._dispatch_tool(
        "run_command", args, "{}", resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5,
        tool_trace=[], convo=[], confirm_command=cards, conversation_id="c1")


async def test_the_tool_loop_passes_arslans_reason_to_an_ordinary_command_card(monkeypatch):
    cards = _Cards()
    await _dispatch(monkeypatch, {"command": "git push origin main", "why": "publish the fix"}, cards)
    [call] = cards.calls
    assert call.get("sandbox") is None and call["why"] == "publish the fix"


async def test_a_reason_is_cut_at_300_and_none_is_empty(monkeypatch):
    cards = _Cards()
    await _dispatch(monkeypatch, {"command": "git push origin main", "why": "x" * 400}, cards)
    await _dispatch(monkeypatch, {"command": "git push origin main"}, cards)
    assert len(cards.calls[0]["why"]) == 300 and "why" not in cards.calls[1]


async def test_the_ordinary_card_frame_carries_the_reason_cleaned(execution_db):
    asker = _Asker()
    with permissions.asking_with(asker):
        await command_confirm.Confirmations("c1").command(
            "git push origin main", [], why="publish" + chr(0x202E) + " the fix" + chr(0x200B))
    [frame] = asker.frames
    assert frame["type"] == "propose_run_command" and "sandbox" not in frame
    assert frame["why"] == "publish the fix" and frame["rule"] == "git-push"


async def test_a_remote_card_carries_it_too(execution_db):
    asker = _Asker()
    with permissions.asking_with(asker):
        await command_confirm.Confirmations("c1").command("uptime", [], remote_host="me@box",
                                                         fingerprints=["SHA256:x"], why="see if the NAS is up")
    assert asker.frames[0]["remote_host"] == "me@box" and asker.frames[0]["why"] == "see if the NAS is up"


async def test_a_card_with_no_reason_has_no_why(execution_db):
    asker = _Asker()
    with permissions.asking_with(asker):
        await command_confirm.Confirmations("c1").command("git push origin main", [])
    assert "why" not in asker.frames[0]


def test_the_frame_cleans_and_cuts_any_reason():
    frame = protocol.propose_run_command("c", "git", ["push"], why="a" + chr(0x2066) + "b\nc" + "d" * 400)
    assert frame["why"].startswith("ab c") and len(frame["why"]) == 300
    outside = protocol.propose_run_command("c", "mv", ["a", "b"], sandbox="outside", why="tidy" + chr(0x202E))
    assert outside["why"] == "tidy"
    assert "why" not in protocol.propose_run_command("c", "ls", [], why="   ")
