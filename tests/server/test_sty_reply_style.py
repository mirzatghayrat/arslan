"""STY (v0.1.64): warm but not fake in chat; four rules for reports (docs/plans/0164/STY-reply-style.md).

These tests pin only that the prompt carries the rules, in the cached stable prefix, and that the
"match the user's register" paragraph is unchanged. Whether replies read better is the user's read
of 20 side-by-side replies plus the M64 bench, not something pytest can show.
"""
from server.orchestrator import arslan

REGISTER = (
    "Match the user's register. When they're just chatting, be casual and human — short, relaxed, a "
    "little warmth, vary your openers. When they bring a task, get crisp. Never answer small talk with "
    "numbered lists."
)

WARM_NOT_FAKE = (
    "not from feeling words: no stock sympathy or pleasantries",
    "don't name their feelings for them",
    "never to show that you remember",
    "Don't give advice about their life unless they ask",
    "Match their length",
    "only when something is really saved (a task list, update_plan, a note)",
)

REPORT_RULES = (
    "lead with the outcome, then the reason",
    "one action per sentence, with numbered steps",
    "call one thing by one name all the way through",
    "say who did it ('I saved the file to …', not 'the file was saved')",
    "Keep words like because and so",
    "These rules are for reports, not for chatting.",
)


def test_the_register_paragraph_is_kept_word_for_word():
    assert REGISTER in arslan._ARSLAN_SYSTEM


def test_warm_not_fake_sits_with_the_register_paragraph():
    for line in WARM_NOT_FAKE:
        assert line in arslan._ARSLAN_SYSTEM, line
    assert arslan._ARSLAN_SYSTEM.index(REGISTER) < arslan._ARSLAN_SYSTEM.index(WARM_NOT_FAKE[0])


def test_report_rules_live_in_the_working_method_not_the_chat_paragraph():
    for line in REPORT_RULES:
        assert line in arslan._CAPABILITY_SELF, line
        assert line not in arslan._ARSLAN_SYSTEM, line


def test_every_new_line_is_in_the_cached_stable_prefix():
    """K3: new text in the per-turn part would break the prompt cache."""
    system = arslan._build_answer_system()
    for line in WARM_NOT_FAKE + REPORT_RULES:
        assert line in system.stable, line
        assert line not in system.volatile, line


def test_a_background_run_ends_with_a_report_in_three_parts():
    text = arslan.BACKGROUND_SYSTEM
    assert "written as a report (outcome first, one action per sentence" in text
    for part in ("what you checked yourself, with the evidence",
                 "what the user should look at, at most one or two things",
                 "what you did not check (not run, failed, or only stated)"):
        assert part in text, part
    assert "concise result" not in text
