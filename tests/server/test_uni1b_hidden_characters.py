"""UNI1b (v0.1.64, the user's option B, 2026-10-31): the characters of a skill's text that show nothing are
counted and marked, never removed and never blocking. The server and the web pass the same cases
(spec/unicode/hidden-characters.json): what is marked, how many, and each run's label in order."""
import json
from pathlib import Path

import pytest

from server.orchestrator import untrusted

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "spec" / "unicode" / "hidden-characters.json")
                     .read_text(encoding="ascii"))["cases"]


RULE = json.loads((Path(__file__).resolve().parents[2] / "spec" / "unicode" / "hidden-characters.json")
                  .read_text(encoding="ascii"))["rule"]


def _summary(case) -> dict:
    labels = list(dict.fromkeys(case["runs"]))
    return {"count": case["count"], "runs": labels[:8], "more": max(0, len(labels) - 8)}


@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_every_shared_case(case):
    runs = untrusted.hidden_runs(case["text"])
    assert [untrusted.hidden_label(cps) for _, cps in runs] == case["runs"]
    assert untrusted.hidden_summary(case["text"]) == _summary(case)


def test_the_tables_are_the_shared_ones():
    """#586 review F6: the rule lives twice (server and web); each side's tables equal the shared file's."""
    assert [list(r) for r in untrusted._HIDDEN] == RULE["hidden"]
    assert [list(r) for r in untrusted._RUN_RANGES] == RULE["run_ranges"]
    assert list(untrusted._PRESENTATION_SELECTORS) == RULE["presentation_selectors"]
    assert [list(r) for r in untrusted._IDEOGRAPHS] == RULE["ideographs"]
    assert [list(r) for r in untrusted._NOT_A_BASE] == RULE["not_a_base"]
    assert list(untrusted._FLAG_TAGS) == RULE["flags"]


def test_every_hidden_range_has_a_case():
    """#586 review F6: each range of the table is reached by at least one case."""
    marked = {cp for c in VECTORS for _, cps in untrusted.hidden_runs(c["text"]) for cp in cps}
    for lo, hi in RULE["hidden"]:
        assert any(lo <= cp <= hi for cp in marked), hex(lo)


def test_the_rule_reads_no_unicode_database(monkeypatch):
    """#586 review F5: a character newer than the server's Unicode (U+1FAE8) is a base like any symbol."""
    import unicodedata
    monkeypatch.setattr(unicodedata, "category", lambda ch: (_ for _ in ()).throw(AssertionError("read")))
    assert untrusted.hidden_summary("\U0001fae8\ufe0f a\ufe0f")["count"] == 1


def test_the_cases_cover_both_sides_of_every_rule():
    names = {c["name"] for c in VECTORS}
    assert len(VECTORS) >= 20 and any(c["count"] == 0 for c in VECTORS) and any(c["count"] > 10 for c in VECTORS)
    assert {"one variation selector after an emoji", "two variation selectors after a letter",
            "a ZWJ inside an emoji sequence", "a ZWNJ between Arabic-script letters",
            "the England flag's tag sequence", "a stray tag character"} <= names


def test_a_run_starts_where_it_is():
    assert [start for start, _ in untrusted.hidden_runs("ab\u200bcd\u2800\u2800")] == [2, 5]


def test_the_summary_keeps_the_whole_count_distinct_labels_and_how_many_more():
    """#586 review F9."""
    text = "".join(f"w{i}\u200b{'' if i % 2 else chr(0x2060)}" for i in range(20))
    out = untrusted.hidden_summary(text, runs_max=3)
    assert out == {"count": 30, "runs": ["U+200B", "U+2060"], "more": 0}       # each label once
    many = "".join(f"w{chr(0xFE00 + i)}" for i in range(12))
    out = untrusted.hidden_summary(many, runs_max=8)
    assert out["count"] == 12 and len(out["runs"]) == 8 and out["more"] == 4


def test_marking_never_changes_what_is_stored():
    case = next(c for c in VECTORS if c["name"] == "the mock's skill text")
    assert untrusted.clean_body(case["text"]) == case["text"]       # UNI1a keeps all of it; UNI1b only counts
