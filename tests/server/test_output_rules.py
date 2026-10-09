"""0.1.58 §2: the answer prompt asks for answers the window can use — code blocks for things
to paste, full local paths (they open in the reader), long deliverables as files with a short
summary — in the cached stable prefix, so it costs nothing per turn."""
from server.orchestrator import arslan


def test_the_output_rules_are_in_the_stable_prefix():
    prefix = arslan._ANSWER_STABLE_PREFIX
    assert arslan._OUTPUT_RULES in prefix
    for phrase in ("fenced code blocks", "full path", "write_file", "2–5 lines"):
        assert phrase in arslan._OUTPUT_RULES, phrase
