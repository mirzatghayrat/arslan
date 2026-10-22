"""compact_saved_context (moved from research_review in C8-1): it may replace only the exact
feedback objects this loop registered, never user text, prior inputs or an oversized draft.
Moved here unchanged from test_research_review.py, which goes with the review in C8-2."""
from server.orchestrator import saved_context


def test_compaction_cannot_touch_user_text_prior_inputs_or_oversized_drafts():
    source = {"role": "user", "content": "full source"}
    lookalike = dict(source)
    saved = {"role": "user", "content": "write succeeded"}
    history = [lookalike, source, saved]
    result = {"url": "https://example.org/", "source": {"id": "receipt"}, "text": "full source"}
    assert not saved_context.compact_saved_context(history, [(source, result)], "x" * 32001)
    assert history[1] is source
    assert saved_context.compact_saved_context(history, [(source, result)], "draft")
    assert source["content"] == lookalike["content"] == "full source"
    assert history[0] is lookalike and history[1] is not source
    assert result["text"] == "full source" and saved["content"] == "write succeeded"
