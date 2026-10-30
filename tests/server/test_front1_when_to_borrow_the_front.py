"""FRONT1 (the user's pick, 2026-10-30): when the model may ask Hands for the front, and what a needs-focus
refusal says.

`_FRONT` describes `front` on desktop_click and desktop_press. It named one condition, an action that "did
nothing (no_effect)", and no released Hands ever said `no_effect` for an action (docs/plans/0164/README.md
§3.6). So the model was never allowed to ask.
- A: it now names the case that does happen. The action came back `sent_unconfirmed`, and the next
  desktop_look said "Nothing changed since your last look." These tests pin those words to the ones the code
  produces.
- B, as the user corrected it: agent-desktop's needs-focus refusal (POLICY_DENIED) is not a trigger.
  - Without `--headed`, agent-desktop skips every step that takes focus or moves the pointer (its pin
    8b792729, crates/macos/src/actions/chain_step_exec.rs:79-83).
  - Arslan never passes `--headed`, and a borrow runs the same command. So asking for the front doesn't help.
  - The refusal now says what agent-desktop says (not delivered), and that the front doesn't change it,
    where it used to say "which Arslan never does".
  - Arslan's own `executed` stays as H2 has it: agent-desktop's codes are maybe-executed.
Hands is faked."""
import pytest

from server.orchestrator import tool_loop
from server.registry import hands_tools
from server.services import hands_contract
from tests.server import test_hands_0153 as base

_case = base._case
isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

#: agent-desktop's needs-focus refusal, as recorded for `type` (tests/fixtures/hands_contract/24_…).
REFUSED = _case("err_type_refused_headless")["envelope"]


# ── A: the words the model waits for ──────────────────────────────────────────

def test_front_names_the_words_hands_and_the_look_really_say():
    assert hands_tools.NOTHING_CHANGED in tool_loop._FRONT
    for word in ("sent_unconfirmed", "no_effect"):
        assert word in hands_contract.OUTCOMES and word in tool_loop._FRONT
    assert "POLICY_DENIED" not in tool_loop._FRONT        # a refusal is no reason to borrow (B)


def test_click_and_press_carry_it_and_typing_has_no_front():
    schemas = tool_loop._NATIVE_PARAM_SCHEMAS
    for key in ("desktop_click", "desktop_press"):
        assert schemas[key]["properties"]["front"]["description"] == tool_loop._FRONT
    assert "front" not in schemas["desktop_type"]["properties"]


# ── B: a needs-focus refusal ─────────────────────────────────────────────────

@pytest.mark.parametrize("command", ["click", "press", "type", "set-value"])
def test_a_needs_focus_refusal_says_it_was_not_delivered_and_the_front_does_not_help(command):
    result = hands_contract.parse_envelope(REFUSED | {"command": command})
    assert result.code == "POLICY_DENIED" and result.hint == "needs_focus"
    assert REFUSED["error"]["disposition"]["delivery"] == "not_delivered"      # what the text repeats
    advice = result.advice()
    assert "agent-desktop did not deliver this" in advice and "front: true does not change that" in advice
    assert "never does" not in advice


@pytest.mark.parametrize("executor, command, args", [
    (hands_tools.DesktopClickExecutor, "click", {"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"}),
    (hands_tools.DesktopPressExecutor, "press", {"app": "Notes", "keys": "tab"}),
])
async def test_the_model_reads_it_on_a_click_and_a_press(hands, asks, in_job, executor, command, args):
    hands.fail_with = REFUSED | {"command": command}
    result = await executor().execute(args)
    assert result["ok"] is False and result["code"] == "POLICY_DENIED"
    assert "agent-desktop did not deliver this" in result["error"]
    assert "front: true does not change that" in result["error"]
    assert "executed" not in result                     # unchanged: H2 keeps agent-desktop's codes maybe-run
