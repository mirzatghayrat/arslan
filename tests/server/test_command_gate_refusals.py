"""The command gate's three refusals that come before any card (hard_rules: forbid-before-card,
heredoc-in-substitution, jxa). Each goes in front of a command that would otherwise ask, so a refusal that moved
behind the card would show one."""
import pytest

from server.orchestrator import command_gate
from server.orchestrator.turn_state import ToolTurn

ASKS = "git push origin main"


@pytest.mark.parametrize("command,says", [
    pytest.param("rm -rf /", "Arslan never runs this", id="forbidden"),
    pytest.param("X=$(cat <<EOF\nhi\nEOF\n)", "A here-document inside $( ) can't run here", id="here-document"),
    pytest.param("osascript -l JavaScript -e x", "JXA (osascript -l JavaScript)", id="JXA"),
])
async def test_refused_before_any_card(command, says):
    cards, frames = [], []

    async def card(*_args, **_own):
        cards.append(_args)
        return True
    turn = ToolTurn(resolve_tools=None, emit=frames.append, tool_timeout_s=5, tool_trace=[], convo=[],
                    confirm_command=card, conversation_id="c1")
    result = await command_gate.check("run_command", {"command": f"{command} ; {ASKS}"}, turn)
    assert result["ok"] is False and result["error"].startswith(says), result
    assert cards == [] and frames == []
