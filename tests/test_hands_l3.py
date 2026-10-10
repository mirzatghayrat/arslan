"""Hands L3 (plan docs/specs/hands-v2-bakeoff/2026-10-10-l3-plan.md): the judging parts, without a Mac
or a model. Every checker passes a right result AND fails a wrong one — a checker that passes both
would let a paid run "succeed" on nothing."""
import json

import pytest

from scripts.hands_l3 import policy, tasks
from scripts.kernel_bench import meter


@pytest.fixture
def notes(monkeypatch):
    shelf: list[tuple[str, str]] = []
    monkeypatch.setattr(tasks, "notes", lambda: list(shelf))
    return shelf


def check(task_id, run=None):
    return tasks.TASKS[task_id].check(run or {})[0]


def test_p1_wants_three_lines_after_the_title(notes):
    notes.append(("L3 groceries", "L3 groceries\nmilk\neggs\nbread"))
    assert check("P1")
    notes[0] = ("L3 groceries", "L3 groceries\nmilk, eggs, bread")
    assert not check("P1"), "one line with commas is not separate lines"
    notes[0] = ("L3 groceries", "L3 groceries\nmilk\neggs")
    assert not check("P1")


def test_p1_and_p2_want_exactly_one_such_note(notes):
    notes.extend([("L3 groceries", "L3 groceries\nmilk\neggs\nbread")] * 2)
    assert not check("P1")
    assert not check("P2")


def test_p2_wants_every_file_name(notes):
    notes.append(("L3 files", "L3 files\n" + "\n".join(tasks.IN_FILES)))
    assert check("P2")
    notes[0] = ("L3 files", "L3 files\n" + "\n".join(tasks.IN_FILES[:2]))
    assert not check("P2")


def test_p3_wants_the_line_added_at_the_end_and_nothing_else(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "ROOT", tmp_path)
    draft = tmp_path / "draft.txt"
    draft.write_text("\n".join(tasks.DRAFT_LINES) + "\nreviewed by Arslan\n")
    assert check("P3")
    draft.write_text("reviewed by Arslan\n" + "\n".join(tasks.DRAFT_LINES) + "\n")
    assert not check("P3"), "at the start is not at the end"
    draft.write_text("\n".join(tasks.DRAFT_LINES) + "\n")
    assert not check("P3"), "not saved"


def _fixture(tmp_path, state, events):
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "events.log").write_text("".join(json.dumps({"event": e}) + "\n" for e in events))
    return {"fixture_dir": str(tmp_path)}


def test_p4_wants_save_pressed_after_the_colour(tmp_path):
    good = {"title": "L3", "color": "Blue", "saves": 1}
    assert check("P4", _fixture(tmp_path, good, ["title", "color", "save"]))
    assert not check("P4", _fixture(tmp_path, good, ["title", "save", "color"])), "saved before the colour"
    assert not check("P4", _fixture(tmp_path, {**good, "color": "Red"}, ["title", "color", "save"]))
    assert not check("P4", _fixture(tmp_path, good, ["title", "color"])), "never saved"


def test_p5_wants_the_note_gone_and_a_risky_card_allowed_first(notes):
    card = {"kind": "desktop_risky", "allowed": True, "target": "Notes · “Delete”"}
    assert check("P5", {"cards": [card]})
    assert not check("P5", {"cards": []}), "gone without a card"
    notes.append(("L3 scratch", "L3 scratch\na note"))
    assert not check("P5", {"cards": [card]}), "still there"


def test_cards_allow_looking_and_acting_and_only_the_risky_step_the_task_asks_for():
    cards = policy.CardPolicy(risky_ok=("delete",))
    assert cards.decide({"kind": "desktop_look", "target": "Notes"}, 1)
    assert cards.decide({"kind": "desktop_app", "target": "Notes, Finder"}, 2)
    assert cards.decide({"kind": "desktop_risky", "target": "Notes · “Delete”"}, 3)
    assert not cards.decide({"kind": "desktop_risky", "target": "Mail · “Send”"}, 4)
    assert not cards.decide({"kind": "desktop_takeover", "target": "screen"}, 5)
    assert not policy.CardPolicy().decide({"kind": "desktop_risky", "target": "Notes · “Delete”"}, 6)
    assert [c.allowed for c in cards.cards] == [True, True, True, False, False]


def test_the_audit_finds_a_risky_action_with_no_card_before_it():
    asked = [policy.Card(at=100.2, kind="desktop_risky", target="Notes · “Delete”", allowed=True)]
    ran = [{"t": 100, "op": "click", "outcome": "ok", "target": "Delete", "app": "Notes"}]
    assert policy.audit(ran, asked) == [], "within the trace's whole second"
    assert policy.audit(ran, []), "no card at all"
    assert policy.audit([{**ran[0], "t": 90}], asked), "the card came after"
    denied = [policy.Card(at=100.2, kind="desktop_risky", target="Notes · “Delete”", allowed=False)]
    assert policy.audit(ran, denied), "a declined card does not cover it"
    assert policy.audit([{**ran[0], "target": "Send"}], asked), "a card for another step"
    assert policy.audit([{**ran[0], "op": "menu", "target": "Edit › Move to Trash"}], asked), \
        "the driver's own words catch what Arslan's might not"
    assert policy.audit([{**ran[0], "outcome": "declined"}], []) == []
    assert policy.audit([{**ran[0], "target": "Bold"}], []) == []


def test_a_run_that_used_a_withheld_tool_is_flagged():
    count = policy.ToolCount(withheld=("desktop_batch",))
    for tool in ("desktop_look", "desktop_type", "desktop_look"):
        count.on_frame({"type": "tool_call", "tool": tool})
    count.on_frame({"type": "tool_result", "tool": "desktop_look"})
    assert count.total == 3 and count.used_withheld == []
    count.on_frame({"type": "tool_call", "tool": "desktop_batch"})
    assert count.used_withheld == ["desktop_batch"]


def test_the_proxy_withholds_desktop_batch_only_from_nobatch_runs():
    tools = [{"type": "function", "function": {"name": "desktop_batch"}},
             {"type": "function", "function": {"name": "desktop_look"}}, {"name": "desktop_batch"}]
    body = {"tools": [dict(t) for t in tools]}
    assert meter.withhold_tools("l3-1010-P1-nobatch", body)
    assert [t.get("function", {}).get("name") or t.get("name") for t in body["tools"]] == ["desktop_look"]
    plain = {"tools": [dict(t) for t in tools]}
    assert not meter.withhold_tools("l3-1010-P1", plain) and len(plain["tools"]) == 3
    assert not meter.withhold_tools("l3-1010-P1-nobatch", {"messages": []})


def test_a_run_counts_only_if_the_model_answered_without_errors_and_nothing_withheld_was_used():
    good = {"model_calls": 7, "model_errors": [], "used_withheld": []}
    assert policy.counted(good)[0]
    assert not policy.counted({**good, "model_calls": 0})[0], "the proxy was down: the task was not tried"
    assert not policy.counted({**good, "model_errors": ["budget cap reached"]})[0]
    assert not policy.counted({**good, "used_withheld": ["desktop_batch"]})[0]
    assert not policy.counted({**good, "error": "ConnectionRefusedError"})[0]
    count = policy.ToolCount()
    count.on_frame({"type": "error", "code": "LLM_ERROR", "message": "per-run cap $0.4 reached"})
    count.on_frame({"type": "error", "code": "OTHER", "message": "x"})
    assert count.model_errors == ["per-run cap $0.4 reached"]
