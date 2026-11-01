"""STY2 (v0.1.64): how Arslan does work, "deeper, not bigger" (docs/plans/0164/STY-reply-style.md § STY2).

Four points go into the working method ("How you work", `_CAPABILITY_SELF`). Three extend K5's lines rather than
start a second list (docs/sessions.md §12 rule 3); one is a new line. `BACKGROUND_SYSTEM` gets one line for points 1-3
and a short "Suggestions, not done" part; STY's three-part ending already carries point 4. The chat paragraph stays
exactly as STY left it. Whether runs get better is the 27-task bench and the "done without evidence" count
(scripts/kernel_bench/done_without_evidence.py), not something pytest can show.
"""
import hashlib
import re

from server.orchestrator import arslan

DEEPER = "Go deeper, not bigger"
RAW = "work from the raw material (the real file, the data, the original page), not from memory, a summary or someone's retelling"
CITE = "each citation points back to the source itself"
RUN = "run what can be run (the tests, the command, opening the file you produced) instead of reasoning that it should work"
EVIDENCE = "Saying it is done needs evidence beyond your own word"
POINTS = (DEEPER, RAW, CITE, RUN, EVIDENCE)

# _ARSLAN_SYSTEM as STY (#452) left it; STY2 must not touch the chat paragraph.
STY_CHAT_SHA256 = "21334772d2debc5b3acb20c79f8533d5c7071b150c2e8f7462ee99a2701439ec"


def _bullets(text: str) -> list[str]:
    return [b for b in re.split(r"\n- ", text)[1:]]


def _bullet_with(text: str, phrase: str) -> str:
    found = [b for b in _bullets(text) if phrase in b]
    assert len(found) == 1, (phrase, found)
    return found[0]


def test_the_four_points_are_in_how_you_work():
    for point in POINTS:
        assert point in arslan._CAPABILITY_SELF, point


def test_three_points_extend_k5s_lines_and_one_is_new():
    text = arslan._CAPABILITY_SELF
    assert RAW in _bullet_with(text, "Read before you change: look at a file or the current state before editing it")
    assert CITE in _bullet_with(text, "cite only sources you actually read in this turn")
    check = _bullet_with(text, "Check after you change: read back what you wrote, or run it, before you say it is done")
    assert RUN in check and EVIDENCE in check
    assert _bullet_with(text, DEEPER).startswith(DEEPER)
    assert len(_bullets(text)) == 14            # K5 and STY's 13 lines, plus "Go deeper, not bigger"


def test_extras_are_suggested_at_the_end_not_built():
    line = _bullet_with(arslan._CAPABILITY_SELF, DEEPER)
    assert "what a top professional would do" in line
    assert "list anything beyond what was asked at the end, as suggestions" in line
    assert "don't widen the scope yourself" in line


def test_the_evidence_line_names_what_counts_and_asks_for_what_was_not_checked():
    check = _bullet_with(arslan._CAPABILITY_SELF, "Check after you change")
    for evidence in ("a passing test", "a command's output", "the file existing", "the source matching"):
        assert evidence in check, evidence
    assert "say plainly what you did not verify" in check


def test_the_chat_paragraph_is_exactly_as_sty_left_it():
    assert hashlib.sha256(arslan._ARSLAN_SYSTEM.encode()).hexdigest() == STY_CHAT_SHA256
    for point in POINTS:
        assert point not in arslan._ARSLAN_SYSTEM, point


def test_every_new_line_is_in_the_cached_stable_prefix():
    system = arslan._build_answer_system()
    for point in POINTS:
        assert point in system.stable, point
        assert point not in system.volatile, point


def test_background_work_gets_one_line_for_points_one_to_three_and_a_suggestions_part():
    text = arslan.BACKGROUND_SYSTEM
    assert "Go deeper, not bigger: work from the raw material, run what can be run, and don't widen the scope" in text
    assert "a short fourth part, 'Suggestions, not done'" in text
    assert text.count("Suggestions, not done") == 1
    # Point 4 is STY's three-part ending, not a second copy.
    assert EVIDENCE not in text
    assert "what you did not check (not run, failed, or only stated)" in text
    # The fourth part comes after the three, and only when there's something real to suggest.
    assert text.index("what you did not check") < text.index("Suggestions, not done")
    assert "only when there is something real to suggest" in text
