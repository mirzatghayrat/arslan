"""Answer-path prompt-cache reorder (spec 2026-07-13, Task 1).

Nails the regression this whole change exists to prevent: the timestamp (and every other
per-turn/per-conversation input) must NEVER live in the cacheable stable prefix. The prefix
is rendered twice with different clocks + different roster/facts/summary/KB and asserted
byte-identical, with all differences confined to the volatile suffix.
"""
import re

from arslan.llm.cached_system import CachedSystem
from server.orchestrator import arslan


def _sys(**kw):
    base = dict(extra_system="", roster="(none)", facts="", summary="", kb_block="")
    base.update(kw)
    return arslan._build_answer_system(**base)


def test_answer_stable_prefix_is_byte_stable_across_clock_and_dynamic(monkeypatch):
    # Render 1: clock A, roster/facts/summary/KB set 1, no addendum.
    monkeypatch.setattr(arslan, "_now_line", lambda: "\n\nDATE=2026-07-13 (Monday). guidance")
    a = _sys(roster="- Alpha (x)", facts="Known facts: likes tea",
             summary="talked about A", kb_block="\n\nKB: doc1")
    # Render 2: DIFFERENT clock, DIFFERENT dynamic content, and a per-turn addendum.
    monkeypatch.setattr(arslan, "_now_line", lambda: "\n\nDATE=2026-12-31 (Wednesday). guidance")
    b = _sys(extra_system="\n\nCLARIFY: ask what they mean",
             roster="- Beta (y)\n- Gamma (z)", facts="Known facts: likes coffee",
             summary="talked about B", kb_block="\n\nKB: doc2")

    assert isinstance(a, CachedSystem) and isinstance(b, CachedSystem)
    # The cacheable prefix is byte-for-byte identical; only the volatile suffix moved.
    assert a.stable == b.stable
    assert a.volatile != b.volatile
    # And the prefix leaks NONE of the dynamic inputs.
    for poison in ("DATE=", "Alpha", "Beta", "likes tea", "likes coffee",
                   "talked about", "KB:", "CLARIFY"):
        assert poison not in a.stable


def test_static_guards_are_all_in_the_stable_prefix():
    s = _sys()
    for guard in (arslan._ARSLAN_SYSTEM, arslan._ANTI_FABRICATION, arslan._NO_BACKGROUND_EXEC,
                  arslan._CLARIFY_CHOICE_NUDGE, arslan._NO_REPASTE, arslan._WEB_TOOL_GUIDANCE,
                  arslan._CAPABILITY_SELF):
        assert guard in s.stable


def test_extra_system_lands_in_volatile_not_stable():
    # extra_system carries per-turn clarify/gather addenda (present some turns, "" others)
    # → it MUST be volatile, never in the cached prefix.
    s = _sys(extra_system="\n\nADDENDUM-XYZ")
    assert "ADDENDUM-XYZ" in s.volatile
    assert "ADDENDUM-XYZ" not in s.stable


def test_all_dynamic_content_present_and_date_line_last():
    s = _sys(roster="- Deck Master (content)", facts="Known facts: uses xhs",
             summary="prior chat", kb_block="\n\nKB block here")
    full = str(s)
    # Everything the pre-reorder prompt carried is still present, just relocated.
    assert "Deck Master" in full and "Your team" in full
    assert "uses xhs" in full
    assert "prior chat" in full
    assert "KB block here" in full
    # The date line is LAST (after the KB block) — the least-cache-poisoning position.
    date_idx = full.index("Current date")
    assert date_idx > full.index("KB block here")


def test_now_line_is_date_level_no_minute():
    line = arslan._now_line()
    assert re.search(r"\d{4}-\d{2}-\d{2}", line)                    # date present
    assert re.search(r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday", line)  # weekday
    assert not re.search(r"\b\d{1,2}:\d{2}\b", line)                # NO minute-level time
    assert "Current date" in line and "date/time" not in line.split(":")[0]
    # Behavior-preserving guidance retained.
    assert "Do NOT search the web for the current date/time" in line
    assert "today" in line and "now" in line
