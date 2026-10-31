"""UNI1b (v0.1.64, the user's option B, 2026-10-31): the characters of a skill's text that show nothing are
counted and marked, never removed and never blocking. The server and the web pass the same cases
(spec/unicode/hidden-characters.json): what is marked, how many, and each run's label in order."""
import json
from pathlib import Path

import pytest

from server.orchestrator import untrusted

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "spec" / "unicode" / "hidden-characters.json")
                     .read_text(encoding="ascii"))["cases"]


@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_every_shared_case(case):
    runs = untrusted.hidden_runs(case["text"])
    assert [untrusted.hidden_label(cps) for _, cps in runs] == case["runs"]
    assert untrusted.hidden_summary(case["text"]) == {"count": case["count"], "runs": case["runs"]}


def test_the_cases_cover_both_sides_of_every_rule():
    names = {c["name"] for c in VECTORS}
    assert len(VECTORS) >= 20 and any(c["count"] == 0 for c in VECTORS) and any(c["count"] > 10 for c in VECTORS)
    assert {"one variation selector after an emoji", "two variation selectors after a letter",
            "a ZWJ inside an emoji sequence", "a ZWNJ between Arabic-script letters",
            "the England flag's tag sequence", "a stray tag character"} <= names


def test_a_run_starts_where_it_is():
    assert [start for start, _ in untrusted.hidden_runs("ab\u200bcd\u2800\u2800")] == [2, 5]


def test_the_summary_keeps_the_first_runs_and_the_whole_count():
    text = "".join(f"w{i}\u200b{'' if i % 2 else chr(0x2060)}" for i in range(20))
    out = untrusted.hidden_summary(text, runs_max=3)
    assert out["count"] == 30 and len(out["runs"]) == 3


def test_marking_never_changes_what_is_stored():
    case = next(c for c in VECTORS if c["name"] == "the mock's skill text")
    assert untrusted.clean_body(case["text"]) == case["text"]       # UNI1a keeps all of it; UNI1b only counts
