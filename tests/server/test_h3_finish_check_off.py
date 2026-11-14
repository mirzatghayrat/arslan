"""H3 (harness plan; the `harness_finish_check` switch, default OFF): with the switch off, a turn is byte-identical to
main's. The golden holds what three turns sent and returned on main d4a20dc8e, recorded before any H3 code existed:
every model request (system, messages, tool choice, tools), every side request, the frames, what was shown and what
the turn returned. Each turn is one H3 would act on with the switch on (a hand-back answer, a declined check the answer
leaves out) or a plain answer.

Regenerate ONLY on purpose: ARSLAN_UPDATE_GOLDEN=1 pytest tests/server/test_h3_finish_check_off.py
"""
import json
import os
from pathlib import Path

import pytest

from server.db.models import Setting
from tests.server.scripted_turn import (  # noqa: F401 — the fixtures
    Reply,
    Turn,
    booted_db_fixture,
    call,
    card,
    run_turn,
    table,
    turn_db_fixture,
)

GOLDEN = Path(__file__).parent / "golden" / "h3_finish_check_off_main.json"
HANDED_BACK = "The link itself is fine. You can run curl with an iPhone user agent and send me the results."
JUDGE_SAYS_YES = json.dumps({"handed_back": True, "steps": [{"text": "run curl with an iPhone UA",
                                                             "tool": "run_command"}]})


def _scenario(name, turn):
    tools = table("run_command", "read_file", "web_search")
    if name == "handed_back":
        return [Reply(HANDED_BACK), Reply(JUDGE_SAYS_YES), Reply("unused")], dict(
            tools=tools, confirm_command=card(turn, "command"))
    if name == "declined_unmentioned":
        return [call("run_command", {"command": "python3 verify.py"}), Reply("Here are the three items from the notes."),
                Reply("unused")], dict(tools=tools, confirm_command=card(turn, "command", answer=False))
    return [Reply("The answer is 42.")], dict(tools=tools, confirm_command=card(turn, "command"))


SCENARIOS = ("handed_back", "declined_unmentioned", "plain")


def _record(turn):
    return {"requests": turn.requests, "legacy": turn.legacy, "frames": turn.frames, "shown": turn.shown,
            "cards": [name for name, _shown, _own in turn.cards],
            "final": turn.returned["final"], "stop_reason": turn.returned["stop_reason"]}


async def _run(name, value, monkeypatch, turn_db):
    if value is not None:
        async with turn_db() as db:
            db.add(Setting(key="harness_finish_check", value=value))
            await db.commit()
    turn = Turn()
    replies, own = _scenario(name, turn)
    await run_turn(turn, monkeypatch, turn_db, replies, **own)
    return json.loads(json.dumps(_record(turn), ensure_ascii=False, default=str))


@pytest.mark.parametrize("value", [None, "false", "", "yes"], ids=["unset", "false", "empty", "not-true"])
@pytest.mark.parametrize("name", SCENARIOS)
async def test_switch_off_is_byte_identical_to_main(name, value, monkeypatch, turn_db):
    got = await _run(name, value, monkeypatch, turn_db)
    if os.environ.get("ARSLAN_UPDATE_GOLDEN") == "1" and value is None:
        recorded = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
        recorded[name] = got
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(recorded, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    want = json.loads(GOLDEN.read_text())[name]
    assert got == want
