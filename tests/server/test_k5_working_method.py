"""K5: a working method that finishes the job (card K5, master plan K-5; ⓪Plan's Q6).

"How you work" (`_CAPABILITY_SELF`, in the stable prefix) gains five lines:
- finish the job;
- read before you change;
- check after you change;
- read the error before changing approach;
- in research, cite only what was read this turn.
The last one is U13's citation rule, which replaces the research review that C8 deletes.
"""
from server.orchestrator import arslan

METHOD = (
    "Finish the job: keep going until what was asked is done",
    "Read before you change: look at a file or the current state before editing it",
    "Check after you change: read back what you wrote, or run it, before you say it is done",
    "When a call fails, read the error first, then change the approach",
    "cite only sources you actually read in this turn, and say plainly what you could not verify",
)


def test_how_you_work_carries_the_working_method():
    for line in METHOD:
        assert line in arslan._CAPABILITY_SELF, line


def test_the_method_is_in_the_cached_stable_part_of_every_answer_system():
    system = arslan._build_answer_system()
    for line in METHOD:
        assert line in system.stable, line


def test_the_citation_rule_reaches_background_work_too():
    background = arslan._build_answer_system(route=arslan.BACKGROUND_SYSTEM)
    assert METHOD[-1] in background.stable
