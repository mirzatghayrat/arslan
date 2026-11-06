"""SMART-3 and SMART-4 (v0.1.64, docs/plans/0164/SMART-feels-smart.md): guide the user when blocked, and follow the
user's focus. Prompt text only, folded into the working method's existing lines (docs/sessions.md §12 rule 3), so no
second list; the chat paragraph is untouched. Whether replies get better is SMART-5's bench
(scripts/kernel_bench/smart_bench.py), not something pytest can show.
"""
import re

from server.orchestrator import arslan

# SMART-3: guide when blocked.
BLOCKED = "When the environment blocks you"
GUIDE = (
    "say what's wrong in one line",
    "give the one step they take and where (which machine or app)",
    "the exact command to paste or the Settings path",
    "System Settings › General › Sharing › Remote Login",
    "`sudo systemsetup -setremotelogin on` works only once Terminal has Full Disk Access",
    "Tell me when it's done and I'll retry.",
)
# SMART-4: follow the user's focus.
ANSWER_FIRST = "answer the question that was asked first: a short question gets one to three sentences"
CORRECTED = "When the user corrects you or asks whether you really checked, admit it in a few words"
NO_OFFER = "Don't end with an offer ('let me know if…', 'want me to…') unless there is a real next step"
AMBIGUOUS = "When what the user refers to could mean two things"
PRIVATE = "Don't open other apps' private settings or data"
UNREAD = "never list a link you didn't read as a source"
POINTS = (BLOCKED, *GUIDE, ANSWER_FIRST, CORRECTED, NO_OFFER, AMBIGUOUS, PRIVATE, UNREAD)


def _bullets(text: str) -> list[str]:
    return re.split(r"\n- ", text)[1:]


def _bullet_with(phrase: str) -> str:
    found = [b for b in _bullets(arslan._CAPABILITY_SELF) if phrase in b]
    assert len(found) == 1, (phrase, found)
    return found[0]


def test_every_point_is_in_how_you_work():
    for point in POINTS:
        assert point in arslan._CAPABILITY_SELF, point


def test_each_point_extends_an_existing_line():
    """Folded, not stacked: each sits in the bullet that already covers its subject."""
    failing = _bullet_with("When a call fails, read the error first, then change the approach")
    assert BLOCKED in failing and all(g in failing for g in GUIDE)
    report = _bullet_with("lead with the outcome, then the reason")
    assert ANSWER_FIRST in report and CORRECTED in report
    assert report.index("These rules are for reports, not for chatting.") < report.index(ANSWER_FIRST)  # for every reply
    assert NO_OFFER in _bullet_with("Act in this reply: when something needs doing, call the tool now")
    ask = _bullet_with("Ask the user only when a choice really needs them")
    assert AMBIGUOUS in ask and PRIVATE in ask
    assert UNREAD in _bullet_with("cite only sources you actually read in this turn")


def test_the_examples_name_the_cases_the_card_lists():
    failing = _bullet_with(BLOCKED)
    for case in ("no SSH", "a missing permission", "a tool that isn't installed", "a machine you can't reach"):
        assert case in failing, case
    # A sandbox stop has its own note (find a way, or ask to leave with a reason), not a command to hand the user.
    assert "sandbox" not in failing
    # Settings first: the command fails in Terminal without Full Disk Access (#673 review).
    assert failing.index("System Settings ›") < failing.index("sudo systemsetup")
    assert "Claude Code: the CLI or the desktop app?" in _bullet_with(AMBIGUOUS)
    assert "~/Library/Application Support" in _bullet_with(PRIVATE) and "unless the user asks" in _bullet_with(PRIVATE)


def test_the_chat_paragraph_is_untouched():
    for point in POINTS:
        assert point not in arslan._ARSLAN_SYSTEM, point


def test_every_new_line_is_in_the_cached_stable_prefix_of_chat_and_background_work():
    for route in (None, arslan.BACKGROUND_SYSTEM):
        system = arslan._build_answer_system(route=route) if route else arslan._build_answer_system()
        for point in POINTS:
            assert point in system.stable, point
            assert point not in system.volatile, point
