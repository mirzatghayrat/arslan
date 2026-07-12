"""Answer-path prompt-cache reorder (spec 2026-07-13, Task 1).

Nails the regression this whole change exists to prevent: the timestamp (and every other
per-turn/per-conversation input) must NEVER live in the cacheable stable prefix. The prefix
is rendered twice with different clocks + different roster/facts/summary/KB and asserted
byte-identical, with all differences confined to the volatile suffix.
"""
import re
from datetime import datetime, timedelta

import pytest

from arslan.llm.cached_system import CachedSystem
from server.orchestrator import arslan


def _freeze_utcnow(monkeypatch, when: datetime):
    """Freeze arslan's ``datetime.utcnow()`` to a fixed instant for _now_line()."""
    class _DT(datetime):
        @classmethod
        def utcnow(cls):
            return when
    monkeypatch.setattr(arslan, "datetime", _DT)


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


def test_now_line_is_hour_level_not_minute_and_not_date_only(monkeypatch):
    # Hour precision (spec 2026-07-13 + L1 adversarial-review fix): the UTC HOUR must be
    # present (date-only broke boundary timezone conversion) but floored to :00 (minute-level
    # would re-poison the trailing cache every request).
    _freeze_utcnow(monkeypatch, datetime(2026, 7, 13, 14, 37))
    line = arslan._now_line()
    assert re.search(r"\d{4}-\d{2}-\d{2}", line)                    # date present
    assert re.search(r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday", line)  # weekday
    assert "14:00" in line                                          # UTC HOUR present, floored
    assert "14:37" not in line                                     # minute floored away (cache-stable)
    # Behavior-preserving guidance retained (and now actually supportable — the hour is there).
    assert "Do NOT search the web for the current date/time" in line
    assert "today" in line and "now" in line
    assert "timezone" in line


_UTC_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):00")


@pytest.mark.parametrize(
    "utc, offset_hours, tz_name, expected_local_date",
    [
        # THE regression case: UTC 07-12 23:30, Beijing (+8) has ALREADY rolled to 07-13.
        # A date-only line ("07-12") made this unanswerable; the hour makes it derivable.
        (datetime(2026, 7, 12, 23, 30), 8, "Beijing", "2026-07-13"),
        # New York (-5), early UTC: local is still the PREVIOUS day.
        (datetime(2026, 7, 13, 3, 30), -5, "New York", "2026-07-12"),
        # Los Angeles (-8), early UTC: previous day, larger negative offset.
        (datetime(2026, 7, 13, 4, 30), -8, "Los Angeles", "2026-07-12"),
        # Same-day control (+8, midday UTC): no boundary crossing.
        (datetime(2026, 7, 13, 12, 30), 8, "Beijing midday", "2026-07-13"),
        # Same-day control (-5, midday UTC).
        (datetime(2026, 7, 13, 15, 0), -5, "New York midday", "2026-07-13"),
    ],
)
def test_now_line_carries_utc_hour_for_boundary_tz_conversion(
    monkeypatch, utc, offset_hours, tz_name, expected_local_date
):
    """The now-line must carry enough (the UTC hour) for the model to derive EVERY user's
    LOCAL date correctly, including across the UTC day boundary. Product serves all timezones,
    so the test proves multiple whole-hour zones — not just UTC. We extract the injected UTC
    date+hour and confirm applying the offset yields the known-correct local date; a date-only
    line has no hour to extract and this test would fail at the regex, pinning the regression."""
    _freeze_utcnow(monkeypatch, utc)
    line = arslan._now_line()
    m = _UTC_RE.search(line)
    assert m, f"now-line must carry UTC date + hour for tz conversion, got: {line!r}"
    y, mo, d, h = (int(g) for g in m.groups())
    utc_from_line = datetime(y, mo, d, h)
    local = utc_from_line + timedelta(hours=offset_hours)
    assert local.strftime("%Y-%m-%d") == expected_local_date, (
        f"{tz_name} (UTC{offset_hours:+d}) at {utc} → derived {local.date()}, "
        f"expected {expected_local_date}"
    )
