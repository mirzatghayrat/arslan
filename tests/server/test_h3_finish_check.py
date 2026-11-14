"""H3 (harness plan; switch `harness_finish_check`): the "handed back" check before a turn's answer stands.

A pre-filter (hand-back phrasing in seven locales), then the turn's own judge request (the acceptance judge's path) over
the answer and the offered tool keys; a declined or blocked step the answer never mentions bounces with no judge. One
bounce a turn at most, never on a forced, wrap-up or budget-soft step, never while a goal is set, and any judge
failure lets the answer stand. Off is proven byte-identical to main in test_h3_finish_check_off.py."""
import json
import types
from dataclasses import dataclass
from typing import Any

import pytest

from server.db.models import Setting
from server.orchestrator import finish_check, tool_loop
from server.orchestrator.turn_state import StepMode, TurnRequest
from tests.server.scripted_turn import (  # noqa: F401 — the fixtures
    Reply,
    Turn,
    booted_db_fixture,
    call,
    card,
    run_turn,
    table,
    turn_db_fixture,
    wrap_up_at_one,
)

TOOLS = ("run_command", "read_file", "web_search")
HANDED_BACK = "The link itself is fine. You can run curl with an iPhone user agent and send me the results."
DONE = "The iPhone request gets a 301 to the store; with force_deeplink=true it gets the scheme page. That is the fix."


def _judge(handed_back=True, steps=None):
    steps = [{"text": "run curl with an iPhone UA", "tool": "run_command"}] if steps is None else steps
    return Reply(json.dumps({"handed_back": handed_back, "steps": steps}))


def _judged(turn):
    return [item for item in turn.legacy if finish_check.JUDGE_MARK in item["system"]]


async def _on(turn_db, value="true"):
    async with turn_db() as db:
        db.add(Setting(key="harness_finish_check", value=value))
        await db.commit()


async def _turn(monkeypatch, turn_db, replies, *, answer=True, **own):
    await _on(turn_db)
    turn = Turn()
    own.setdefault("tools", table(*TOOLS))
    own.setdefault("confirm_command", card(turn, "command", answer=answer))
    await run_turn(turn, monkeypatch, turn_db, replies, **own)
    return turn


# ---- Stage 1: the pre-filter, a hit and a miss in each locale ----

CUE_CASES = {
    "en": ("Have ops run steps 2-3 and send me the results.",
           "The server returns a 301 to the App Store for the iPhone user agent."),
    "zh-Hans": ("接下来你可以运行 curl 再确认一下。", "原因是服务器对 iPhone 返回了 301 跳转。"),
    "zh-Hant": ("你可以執行 curl 再確認一次。", "原因是伺服器對 iPhone 回傳了 301 轉址。"),
    "ja": ("curl で実行してみてください。", "サーバーが iPhone に 301 を返しているのが原因です。"),
    "es": ("Puedes ejecutar curl para comprobarlo.", "La causa es que el servidor devuelve un 301 al iPhone."),
    "fr": ("Vous pouvez exécuter curl pour vérifier.", "La cause est que le serveur renvoie un 301 à l’iPhone."),
    "de": ("Führen Sie curl mit einem iPhone-User-Agent aus.",
           "Die Ursache ist, dass der Server dem iPhone einen 301 zurückgibt."),
}


def test_the_cue_lists_cover_the_seven_locales():
    assert set(finish_check.CUES) == set(CUE_CASES)


@pytest.mark.parametrize("locale", list(CUE_CASES))
def test_the_pre_filter_hits_hand_back_phrasing_and_misses_a_plain_answer(locale):
    hit, miss = CUE_CASES[locale]
    assert finish_check.cue_hit(hit) is not None
    assert finish_check.cue_hit(miss) is None


def test_the_pre_filter_reads_curly_apostrophes_and_any_case():
    assert finish_check.cue_hit("I’D RECOMMEND YOU check the AASA file.") is not None


# ---- Stage 2: the judge's JSON, as it is counted ----

OFFERED = {"run_command", "read_file"}


@pytest.mark.parametrize("decision,counted", [
    ({"handed_back": True, "steps": [{"text": "run curl", "tool": "run_command"}]}, ["run curl"]),
    ({"handed_back": True, "steps": [{"text": "run curl", "tool": "run_command"},
                                     {"text": "approve the change", "tool": None},
                                     {"text": "open the page", "tool": "browser_open"},
                                     {"text": "read it", "tool": 3}]}, ["run curl"]),
    ({"handed_back": True, "steps": [{"text": "log in to the console", "tool": None},
                                     {"text": "pay the invoice", "tool": None}]}, []),
    ({"handed_back": False, "steps": [{"text": "run curl", "tool": "run_command"}]}, []),
    ({"handed_back": "yes", "steps": [{"text": "run curl", "tool": "run_command"}]}, []),
    ({"handed_back": True, "steps": "run curl"}, []),
    (["handed_back"], []),
    (None, []),
], ids=["offered", "only-offered-count", "user-only", "judge-says-no", "not-a-bool", "steps-not-a-list",
        "not-an-object", "null"])
def test_only_steps_an_offered_tool_can_do_count(decision, counted):
    assert [step["text"] for step in finish_check.counted_steps(decision, OFFERED)] == counted


# ---- Through a whole turn ----

async def test_a_hand_back_with_an_offered_tool_is_bounced_once(monkeypatch, turn_db):
    turn = await _turn(monkeypatch, turn_db, [Reply(HANDED_BACK), _judge(), Reply(DONE)])
    assert len(turn.requests) == 2 and len(_judged(turn)) == 1
    judged = _judged(turn)[0]["user"]
    assert all(key in judged for key in TOOLS) and HANDED_BACK in judged
    bounced, note = turn.requests[1]["messages"][-2:]
    assert bounced["content"] == HANDED_BACK and note["role"] == "user"
    assert "run curl with an iPhone UA" in note["content"] and "run_command" in note["content"]
    assert turn.returned["final"] == DONE


@pytest.mark.parametrize("judge", [
    _judge(False),
    _judge(True, [{"text": "approve the release", "tool": None}]),
    _judge(True, [{"text": "open it in a browser", "tool": "browser_open"}]),
], ids=["not-handed-back", "user-only-step", "tool-not-offered"])
async def test_no_counted_step_lets_the_answer_stand(judge, monkeypatch, turn_db):
    turn = await _turn(monkeypatch, turn_db, [Reply(HANDED_BACK), judge, Reply("unused")])
    assert len(turn.requests) == 1 and len(_judged(turn)) == 1
    assert turn.returned["final"] == HANDED_BACK


async def test_no_cue_means_no_judge(monkeypatch, turn_db):
    turn = await _turn(monkeypatch, turn_db, [Reply(DONE), Reply("unused")])
    assert len(turn.requests) == 1 and turn.legacy == []
    assert turn.returned["final"] == DONE


async def test_at_most_one_bounce_a_turn(monkeypatch, turn_db):
    again = "You could try the trailing-slash variant and send me the results."
    turn = await _turn(monkeypatch, turn_db, [Reply(HANDED_BACK), _judge(), Reply(again), _judge(), Reply("unused")])
    assert len(turn.requests) == 2 and len(_judged(turn)) == 1
    assert turn.returned["final"] == again


@pytest.mark.parametrize("judge", [Reply("not json at all"), Reply("```json\n{\"handed_back\": tru"),
                                   Reply(None, raises=RuntimeError("judge down"))],
                         ids=["bad-json", "cut-json", "error"])
async def test_a_judge_failure_lets_the_answer_stand(judge, monkeypatch, turn_db):
    turn = await _turn(monkeypatch, turn_db, [Reply(HANDED_BACK), judge, Reply("unused")])
    assert len(turn.requests) == 1 and len(_judged(turn)) == 1
    assert turn.returned["final"] == HANDED_BACK


async def test_a_judge_timeout_lets_the_answer_stand(monkeypatch, turn_db):
    monkeypatch.setattr(finish_check, "JUDGE_TIMEOUT_S", 0)
    turn = await _turn(monkeypatch, turn_db, [Reply(HANDED_BACK), _judge(), Reply("unused")])
    assert len(turn.requests) == 1 and turn.returned["final"] == HANDED_BACK


# ---- The run-341 shape: a declined or blocked step the answer leaves out ----

LEFT_OUT = "Here are the three items from the notes."


async def test_a_declined_check_the_answer_leaves_out_is_bounced_with_no_judge(monkeypatch, turn_db):
    said = "The verify script was declined, so the read-back is unverified."
    turn = await _turn(monkeypatch, turn_db, [call("run_command", {"command": "python3 verify.py"}),
                                              Reply(LEFT_OUT), Reply(said)], answer=False)
    assert turn.legacy == [] and len(turn.requests) == 3
    note = turn.requests[2]["messages"][-1]["content"]
    assert "python3 verify.py" in note and "declined" in note
    assert turn.returned["final"] == said


async def test_a_refused_command_the_answer_leaves_out_is_bounced(monkeypatch, turn_db):
    turn = await _turn(monkeypatch, turn_db, [call("run_command", {"command": "rm -rf /"}),
                                              Reply(LEFT_OUT), Reply("That command was refused.")])
    assert turn.legacy == [] and len(turn.requests) == 3
    assert "rm -rf /" in turn.requests[2]["messages"][-1]["content"]


async def test_a_sandbox_block_the_answer_leaves_out_is_bounced(monkeypatch, turn_db):
    stopped = {"ok": False, "sandbox_denied": True, "error": "the sandbox stopped this command (Operation not permitted)"}
    turn = await _turn(monkeypatch, turn_db, [call("run_command", {"command": "curl https://example.test"}),
                                              Reply(LEFT_OUT), Reply("The sandbox stopped the curl check.")],
                       answers={"run_command": stopped})
    assert turn.legacy == [] and len(turn.requests) == 3
    assert "sandbox" in turn.requests[2]["messages"][-1]["content"]


@pytest.mark.parametrize("answer", [
    "You declined the verify script, so the read-back is unverified.",
    "`python3 verify.py` did not run; the result is unverified.",
    "验证脚本被拒绝了，所以没有核实。",
], ids=["says-declined", "names-the-command", "zh"])
async def test_a_declined_check_the_answer_mentions_stands(answer, monkeypatch, turn_db):
    turn = await _turn(monkeypatch, turn_db, [call("run_command", {"command": "python3 verify.py"}),
                                              Reply(answer), Reply("unused")], answer=False)
    assert len(turn.requests) == 2 and turn.returned["final"] == answer


# ---- Never on forced, wrap-up or budget-soft steps; never with a goal ----

async def test_never_on_a_forced_step(monkeypatch, turn_db):
    turn = await _turn(monkeypatch, turn_db, [call("read_file", {"path": "a.md"}), Reply(HANDED_BACK), _judge(),
                                              Reply("unused")], max_tool_calls=1)
    assert _judged(turn) == [] and turn.returned["final"] == HANDED_BACK


async def test_never_past_the_soft_limit(monkeypatch, turn_db):
    turn = await _turn(monkeypatch, turn_db, [call("read_file", {"path": "a.md"}), Reply(HANDED_BACK), _judge(),
                                              Reply("unused")], budget=wrap_up_at_one())
    assert _judged(turn) == [] and turn.returned["final"] == HANDED_BACK


async def test_never_on_a_forced_step_even_after_a_decline(monkeypatch, turn_db):
    turn = await _turn(monkeypatch, turn_db, [call("run_command", {"command": "python3 verify.py"}),
                                              Reply(LEFT_OUT), Reply("unused")], answer=False, max_tool_calls=1)
    assert len(turn.requests) == 2 and turn.returned["final"] == LEFT_OUT


@dataclass(frozen=True, slots=True)
class _GoalRequest(TurnRequest):
    goal: Any = None          # L7's field on TurnRequest (#857), not on main yet


async def test_off_while_a_goal_is_set(monkeypatch, turn_db):
    monkeypatch.setattr(tool_loop, "TurnRequest", _GoalRequest)
    turn = await _turn(monkeypatch, turn_db, [Reply(HANDED_BACK), _judge(), Reply("unused")], goal=object())
    assert _judged(turn) == [] and turn.returned["final"] == HANDED_BACK


async def test_with_no_goal_the_same_request_type_is_checked(monkeypatch, turn_db):
    monkeypatch.setattr(tool_loop, "TurnRequest", _GoalRequest)
    turn = await _turn(monkeypatch, turn_db, [Reply(HANDED_BACK), _judge(), Reply(DONE)], goal=None)
    assert len(_judged(turn)) == 1 and turn.returned["final"] == DONE


def _state(**own):
    budget = types.SimpleNamespace(soft_reached=lambda: own.pop("soft", False))
    recovery = types.SimpleNamespace(finish_checked=False)
    return types.SimpleNamespace(budget=budget, recovery=recovery, tool_trace=[], wired_keys=set(TOOLS),
                                 adapter=None, **own)


@pytest.mark.parametrize("mode", [
    StepMode(forced=True, finishing=False, saved=False, no_progress=False, truncation_stop=False),
    StepMode(forced=False, finishing=True, saved=False, no_progress=True, truncation_stop=False),
], ids=["forced", "finish-mode wrap-up"])
async def test_the_gate_skips_forced_and_wrap_up_steps_before_reading_the_switch(mode, monkeypatch):
    async def never():
        raise AssertionError("the switch is read only on a step the check may act on")
    monkeypatch.setattr(finish_check, "enabled", never)
    request = types.SimpleNamespace()
    assert await finish_check.check(request, _state(), mode, HANDED_BACK) is None
