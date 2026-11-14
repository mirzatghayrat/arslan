"""An empty final message never reaches the user. A background job's turn that the hard limit ends (a real run: a
command refused by the rules, cards nobody answered, then the dollar cap with no text from the model) used to post
only "nothing was written up". The host now closes it from the turn's own records: what was done, what was blocked
(refusals, cards declined, cards nobody answered), and what is left."""
import pytest

from arslan.execution_budget import Budget, BudgetExceeded, Limits, current, scope
from arslan.models import LLMResponse
from server.orchestrator import answer_salvage, command_gate, tool_gates, tool_loop
from server.orchestrator.turn_plan import Plan
from server.services import approvals, background_jobs, permissions, runtime_messages
from tests.server import test_trajectory_golden as golden

REFUSED = "rm -rf /"
DECLINED = "git push origin main"
UNANSWERED = "git push origin release"
REQUEST = "Check this Mac's disk and write a report"


class _Priced:
    """A model that charges each reply, as the real adapter does: the request first, then its price."""

    def __init__(self, replies, usd=0.25):
        self.replies, self.usd, self.calls = list(replies), usd, 0

    async def chat(self, system, user, history=None, tools=None, **kw):
        current().model_request(100)
        self.calls += 1
        current().charge_usd(self.usd)
        return self.replies.pop(0)


def _call(name, args, cid):
    return LLMResponse(usage={}, content=None, tool_calls=[golden._tc(name, args, cid)])


async def _card(command, argv, **kw):
    """The window's card for a command: the user says no to one, and nobody answers the other (what
    permissions.decide records in each case)."""
    if command == UNANSWERED:
        approvals.LAST_OUTCOME.set("expired")
        permissions.LAST_DECISION.set(permissions.Decision(
            False, "expired", model_text=permissions._EXPIRED.format(title=f"Run `{command}`?", minutes=30)))
    else:
        permissions.LAST_DECISION.set(permissions.Decision(
            False, "user", model_text=permissions._declined_text(f"Run `{command}`?", "")))
    return False


def _wire(monkeypatch):
    golden._pin_workspace(monkeypatch)

    async def yes():
        return True

    async def no():
        return False

    async def none(*_a):
        return None

    async def en():
        return "en"
    monkeypatch.setattr(tool_gates, "_writing_in_own_folder", yes)
    monkeypatch.setattr(command_gate, "_sandbox_enabled", yes)
    monkeypatch.setattr(command_gate, "_asks_for_everything", no)
    monkeypatch.setattr(command_gate, "_outside_grant", none)
    monkeypatch.setattr(runtime_messages, "selected_locale", en)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "write_file", golden._Write())


async def _resolve():
    return [{"key": "run_command", "description": "r"}, {"key": "write_file", "description": "w"}]


def _run_328_shape():
    """A refusal, a declined card, a saved file, a card nobody answered, then a reply with no text."""
    return [_call("run_command", {"command": REFUSED}, "r1"),
            _call("run_command", {"command": DECLINED}, "r2"),
            _call("write_file", {"path": "Reports/data.txt", "content": "a"}, "w1"),
            _call("run_command", {"command": UNANSWERED}, "r3"),
            LLMResponse(usage={}, content="", tool_calls=[])]


async def _turn(monkeypatch, replies, *, usd_cap=1.0, in_job=True):
    _wire(monkeypatch)
    monkeypatch.setattr(background_jobs, "inside_job", lambda: in_job)
    model = _Priced(replies)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    chunks = []
    from server.orchestrator.tool_caller import ToolCaller
    with scope(Budget(Limits(), usd_cap=usd_cap)):
        result = await tool_loop.run_native(
            system="S", user_content=REQUEST, history=[], emit=lambda e: None, on_chunk=chunks.append,
            resolve_tools=_resolve, confirm_command=_card,
            caller=ToolCaller(actor="host", spawn_id=None, conversation_id="c"))
    return result, "".join(chunks), model


async def test_a_job_turn_the_dollar_cap_ends_with_no_text_closes_from_its_records(monkeypatch):
    with pytest.raises(BudgetExceeded) as stopped:
        await _turn(monkeypatch, _run_328_shape())
    closing = stopped.value.closing
    assert closing.strip(), "the job's report must not be empty"
    assert "dollar" in str(stopped.value) or "usd" in str(stopped.value)
    done, blocked, left = (closing.index(head) for head in ("Done", "Blocked:", "Left"))
    assert done < blocked < left
    assert "write_file" in closing[done:blocked] and "Reports/data.txt" in closing[done:blocked]
    section = closing[blocked:left]
    assert f"refused by Arslan's rules: run_command `{REFUSED}`" in section
    assert f"you said no: run_command `{DECLINED}`" in section
    assert f"nobody answered the card: run_command `{UNANSWERED}`" in section
    assert REQUEST in closing[left:]


async def test_the_same_turn_in_chat_keeps_its_own_closing(monkeypatch):
    """Outside a job, the chat turn's closing (0.1.50) is unchanged: this fix is the job's."""
    result, streamed, _ = await _turn(monkeypatch, _run_328_shape(), in_job=False)
    assert result["final"] == streamed
    assert result["final"].startswith("I stopped here: this turn reached its work limit (dollar limit).")
    assert "Blocked:" not in result["final"]


async def test_a_job_turn_that_answers_keeps_its_answer_byte_for_byte(monkeypatch):
    answer = "Report saved to Reports/data.txt.\nTwo commands were not run."
    replies = [_call("write_file", {"path": "Reports/data.txt", "content": "a"}, "w1"),
               LLMResponse(usage={}, content=answer, tool_calls=[])]
    result, streamed, _ = await _turn(monkeypatch, replies, usd_cap=10.0)
    assert result["final"] == answer and streamed == answer


def _nothing_ran_shape():
    """Every call blocked (a refusal, two declined cards, a card nobody answered), then the cap: no call succeeded."""
    return [_call("run_command", {"command": REFUSED}, "r1"),
            _call("run_command", {"command": DECLINED}, "r2"),
            _call("run_command", {"command": UNANSWERED}, "r3"),
            _call("run_command", {"command": UNANSWERED + " --tags"}, "r4"),
            LLMResponse(usage={}, content="", tool_calls=[])]


async def test_a_chat_turn_the_cap_ends_with_no_successful_call_closes_in_the_chat(monkeypatch):
    """The chat turn used to raise here (nothing had run, so there was nothing to name) and the user saw no
    closing. It now ends with the chat's closing, then what its records show: done, blocked and left."""
    result, streamed, model = await _turn(monkeypatch, _nothing_ran_shape(), in_job=False)
    final = result["final"]
    assert final == streamed, "the closing reaches the chat"
    assert result["stop_reason"] == "task_budget_exhausted" and model.calls == 4
    assert final.startswith("I stopped here: this turn reached its work limit (dollar limit). Nothing was saved yet")
    records = final[final.index("From this run's own records:"):]
    done, blocked, left = (records.index(head) for head in ("Done: no tool call succeeded.", "Blocked:", "Left"))
    assert done < blocked < left
    section = records[blocked:left]
    assert f"refused by Arslan's rules: run_command `{REFUSED}`" in section
    assert f"you said no: run_command `{DECLINED}`" in section
    assert f"nobody answered the card: run_command `{UNANSWERED}`" in section
    assert f"you said no: run_command `{UNANSWERED} --tags`" in section
    assert records.endswith(f"Left: the request itself, {REQUEST}")


async def test_a_closing_that_cannot_be_written_never_replaces_the_stop(monkeypatch, caplog):
    """The records builder runs while a stop propagates: its own failure is logged loudly (an error, with its
    traceback), and the stop still ends the job's turn as a budget stop, and the chat turn with its closing."""
    def broken(*_a, **_k):
        raise TypeError("a bug in the builder")
    monkeypatch.setattr(answer_salvage, "_records_closing", broken)
    with caplog.at_level("ERROR", logger=tool_loop.logger.name), pytest.raises(BudgetExceeded) as stopped:
        await _turn(monkeypatch, _run_328_shape())
    assert stopped.value.closing == ""
    errors = [r for r in caplog.records if r.levelname == "ERROR" and "closing not written" in r.getMessage()]
    assert errors and errors[0].exc_info and errors[0].exc_info[0] is TypeError
    result, streamed, _ = await _turn(monkeypatch, _nothing_ran_shape(), in_job=False)
    assert result["final"] == streamed and result["final"].startswith("I stopped here")


# --- the records the closing is made of -------------------------------------------------------------------------

async def _real_refusals() -> list[dict]:
    """Each blocked kind as its own producer writes it, so a reworded producer fails here, not in the field."""
    from server.orchestrator.turn_state import ToolTurn

    async def unused(*_a, **_k):
        raise AssertionError("no card before a refusal")
    turn = ToolTurn(resolve_tools=None, emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                    confirm_command=unused, conversation_id="c1")
    refused = await command_gate.check("run_command", {"command": REFUSED}, turn)
    approvals.LAST_OUTCOME.set("expired")
    expired_gate = tool_gates._declined("user declined this command", "this command")
    approvals.LAST_OUTCOME.set(None)
    return [{"tool": "run_command", "args": {"command": REFUSED}, "result": refused},
            {"tool": "run_command", "args": {"command": "a"},
             "result": {"ok": False, "error": permissions._declined_text("Run `a`?", "")}},
            {"tool": "run_command", "args": {"command": "b"},
             "result": {"ok": False, "error": permissions._declined_text("Run `b`?", "not now")}},
            {"tool": "write_file", "args": {"path": "x"},
             "result": {"ok": False, "error": tool_gates._declined("the user declined writing x", "writing x")}},
            {"tool": "run_command", "args": {"command": "c"},
             "result": {"ok": False, "error": permissions._EXPIRED.format(title="Run `c`?", minutes=30)}},
            {"tool": "run_command", "args": {"command": "d"}, "result": {"ok": False, "error": expired_gate}},
            {"tool": "run_command", "args": {"command": "e"},
             "result": {"ok": False, "error": permissions._UNATTENDED.format(title="Run `e`")}}]


async def test_each_blocked_kind_is_named_from_the_producers_own_words():
    kinds = [answer_salvage._blocked_kind(step["result"]) for step in await _real_refusals()]
    assert kinds == ["refused", "declined", "declined", "declined", "unanswered", "unanswered", "unanswered"]


def test_a_failure_that_is_not_a_block_is_not_listed():
    assert answer_salvage._blocked_kind({"ok": False, "error": "exit 1: no such file"}) is None
    assert answer_salvage._blocked_kind({"ok": True, "summary": "Nobody answered the card"}) is None


async def test_left_lists_the_plan_steps_not_done_or_else_the_request():
    plan = Plan()
    plan.update({"items": [{"text": "collect disk data", "status": "done"},
                           {"text": "build the report", "status": "in_progress"},
                           {"text": "check the tags", "status": "pending"}]})
    text = answer_salvage._records_closing(REQUEST, await _real_refusals(), plan.items, locale="en")
    left = text[text.index("Left"):]
    assert "build the report" in left and "check the tags" in left and "collect disk data" not in left
    assert REQUEST not in left
    assert REQUEST in answer_salvage._records_closing(REQUEST, [], [], locale="en")


def test_left_says_only_the_answer_is_missing_when_every_plan_step_is_done():
    plan = Plan()
    plan.update({"items": [{"text": "collect disk data", "status": "done"},
                           {"text": "build the report", "status": "done"}]})
    text = answer_salvage._records_closing(REQUEST, [], plan.items, locale="en")
    assert text.endswith("Left: every plan step is done; only the final answer was not written.")
    assert REQUEST not in text and "collect disk data" not in text


def test_one_successful_call_is_one_tool_call():
    trace = [{"tool": "run_command", "args": {"command": "df -h"}, "result": {"ok": True, "exit_code": 0}}]
    text = answer_salvage._records_closing(REQUEST, trace, [], locale="en")
    assert "Done: 1 tool call succeeded (run_command ×1)." in text and "1 tool calls" not in text
    two = answer_salvage._records_closing(REQUEST, trace * 2, [], locale="en")
    assert "Done: 2 tool calls succeeded (run_command ×2)." in two


async def test_unanswered_cards_are_counted_apart_from_refusals():
    text = answer_salvage._records_closing(REQUEST, await _real_refusals(), [], locale="en")
    assert text.count("nobody answered the card:") == 3
    assert text.count("you said no:") == 3 and text.count("refused by Arslan's rules:") == 1


def test_done_counts_the_receipts_and_names_what_was_saved():
    trace = [{"tool": "run_command", "args": {"command": "df -h"}, "result": {"ok": True, "exit_code": 0}},
             {"tool": "run_command", "args": {"command": "du"}, "result": {"ok": True, "exit_code": 0}},
             {"tool": "write_file", "args": {"path": "r.html"}, "result": {"ok": True, "path": "r.html"}},
             {"tool": "run_command", "args": {"command": "x"}, "result": {"ok": False, "error": "exit 1"}}]
    text = answer_salvage._records_closing(REQUEST, trace, [], locale="en")
    done = text[text.index("Done"):text.index("Left")]
    assert "3 tool calls succeeded" in done and "run_command ×2" in done and "Saved: r.html" in done
    assert "Blocked" not in text, "nothing was blocked: no empty section"
    assert "no tool call succeeded" in answer_salvage._records_closing(REQUEST, [], [], locale="en")


@pytest.mark.parametrize("locale", list(runtime_messages.MESSAGES))
async def test_every_locale_closes_with_the_three_parts(locale):
    text = answer_salvage._records_closing(REQUEST, await _real_refusals(), [], locale=locale)
    for key in ("records_header", "records_blocked", "records_refused", "records_declined", "records_unanswered"):
        assert runtime_messages.render(key, locale) in text
