"""The command gate's three refusals that come before any card (hard_rules: forbid-before-card,
heredoc-in-substitution, jxa). Each goes in front of a command that would otherwise ask, so a refusal that moved
behind the card would show one. They come before where the command would run is worked out, too: no sandbox setting
and no grant is read for a command that never runs."""
import pytest

from server.orchestrator import command_gate
from server.orchestrator.turn_state import ToolTurn

ASKS = "git push origin main"
NEVER_RUNS = [
    pytest.param("rm -rf /", "Arslan never runs this", id="forbidden"),
    pytest.param("X=$(cat <<EOF\nhi\nEOF\n)", "A here-document inside $( ) can't run here", id="here-document"),
    pytest.param("osascript -l JavaScript -e x", "JXA (osascript -l JavaScript)", id="JXA"),
    pytest.param("find . -exec rm -rf / \\;", "Arslan never runs this", id="forbidden-find-exec"),
    pytest.param("echo a | xargs -I{} rm -rf ~", "Arslan never runs this", id="forbidden-xargs"),
]


def _turn(cards, frames):
    async def card(*_args, **_own):
        cards.append(_args)
        return True
    return ToolTurn(resolve_tools=None, emit=frames.append, tool_timeout_s=5, tool_trace=[], convo=[],
                    confirm_command=card, conversation_id="c1")


@pytest.mark.parametrize("command,says", NEVER_RUNS)
async def test_refused_before_any_card(command, says):
    cards, frames = [], []
    result = await command_gate.check("run_command", {"command": f"{command} ; {ASKS}"}, _turn(cards, frames))
    assert result["ok"] is False and result["error"].startswith(says), result
    assert cards == [] and frames == []


@pytest.mark.parametrize("command,says", NEVER_RUNS)
async def test_refused_before_the_sandbox_setting_or_a_grant_is_read(command, says, monkeypatch):
    """Even asked to leave the sandbox, with the setting unreadable and a grant stored: the refusal answers, and
    neither is read."""
    read = []

    async def unreadable():
        read.append("sandbox setting")
        raise RuntimeError("the settings can't be read")

    async def a_grant(*_args):
        read.append("grant")
        return object()
    monkeypatch.setattr(command_gate, "_sandbox_enabled", unreadable)
    monkeypatch.setattr(command_gate, "_outside_grant", a_grant)
    cards, frames = [], []
    args = {"command": command, "outside_sandbox": True, "why": "it needs the keychain"}
    result = await command_gate.check("run_command", args, _turn(cards, frames))
    assert result["ok"] is False and result["error"].startswith(says), result
    assert read == [] and cards == [] and frames == []
