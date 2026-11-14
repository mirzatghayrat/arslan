"""S64-0, gap 1, after v0.1.64 SUB6: what a helper read on the web came back unframed and unmarked. SUB6 deleted the
helpers; a sub-session's report is what now brings another run's reading into a turn, so S64-0's three tests check it:
the helper became a sub-session, and the turn after the helper (the parent turn) became the commander's summary turn.
The assertions are the old ones: the report is framed as outside content, Arslan's own note (`memory_note`) does not
take effect by itself in the summary turn, and a command there that reaches the network shows a card first.

SUB4's tests cover the same ground (test_sub4_report.py: the framing in
`test_results_stay_in_each_sub_session_and_the_commander_gets_one_summary_with_each_report_framed`, the note and the
card together in `test_a_report_from_a_child_that_read_outside_content_starts_the_summary_flagged`). These keep S64-0's
one test per consequence, on SUB4's harness: real jobs, the real summary turn and tool loop, a scripted model. The
clean counterpart is test_s64_0_outside_content_gaps.py's `test_a_clean_turn_is_unchanged` and SUB4's "clean" case.
"""
import json

import pytest
from sqlalchemy import select

from server.db.models import MemoryEntry
from server.orchestrator import untrusted
from server.registry import executors
from tests.server.test_s64_0_outside_content_gaps import POISON, _Run, memory  # noqa: F401  (the fixture)
from tests.server.test_sub4_report import (  # noqa: F401  (the fixtures)
    COMMAND, NOTE_ADD, OUTLINE, PAGE, ROOT, _cards, _children, _fresh, _Model, _settled, _sink, _start, _steps,
    _summaries, _wait, runs)

#: NET-a: the mark read through S2a-1's network card, its switch off (tests/server/test_net_a_gate.py has NET-a's).
pytestmark = pytest.mark.usefixtures("s2a1_network_rule")


def _a_child_reads_a_page(monkeypatch, *summary_steps) -> _Model:
    """One sub-session reads a (poisoned) page and repeats it in its result; the summary turn takes `summary_steps`."""
    model = _Model({OUTLINE: _steps(PAGE, final=f"Read the setup page. {POISON}")},
                   summary=_steps(*summary_steps, final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    return model


async def test_a_sub_sessions_report_reaches_the_summary_turn_inside_the_web_content_frame(runs, monkeypatch):  # noqa: F811
    _sink(ROOT)
    model = _a_child_reads_a_page(monkeypatch)
    await _start(OUTLINE)
    await _wait(_settled)
    [child], [summary] = _children(), _summaries()
    assert child.external_seen is True and summary.external_seen is True
    sent = json.dumps(model.requests["summary"][0]["user"], ensure_ascii=False)
    start = sent.index("evil@example.com")
    assert sent.rfind(untrusted.DELIM_OPEN, 0, start) > sent.rfind(untrusted.DELIM_CLOSE, 0, start), \
        "the sub-session's words sit inside an EXTERNAL_WEB_CONTENT frame"
    assert untrusted.TOOL_OPEN not in sent[:start][-400:], "framed as web content, not as tool output"


async def test_after_a_sub_sessions_report_arslans_own_note_waits_for_the_user(runs, monkeypatch):  # noqa: F811
    _sink(ROOT)
    _a_child_reads_a_page(monkeypatch, NOTE_ADD)
    await _start(OUTLINE)
    await _wait(_settled)
    async with runs() as db:
        assert list((await db.scalars(select(MemoryEntry.status))).all()) == ["proposed"]


async def test_after_a_sub_sessions_report_a_command_that_reaches_the_network_asks_first(runs, monkeypatch):  # noqa: F811
    runner = _Run()
    monkeypatch.setitem(executors.EXECUTORS, "run_command", runner)
    shown = _sink(ROOT)                                    # every card answered yes
    _a_child_reads_a_page(monkeypatch, COMMAND)
    await _start(OUTLINE)
    await _wait(_settled)
    assert [card.get("perm_kind") for card in _cards(shown)] == ["network"]
    assert runner.runs == [(False, False)]                 # the user said yes: it ran with the network
