"""Compact a turn's earlier web reads once a research report is saved.

Moved verbatim from `research_review` in C8-1 (v0.1.63): it is not part of the review.
After a successful `write_file` of a report, every provider that does not clear old tool
results itself (all but Claude's native path, K3b) gets receipts in place of the web-page
bodies it already used. tests/server/test_saved_context_identity.py pins the model's
context after a save byte for byte against the pre-move code.
"""
import json

from server.orchestrator.untrusted import wrap_external


def compact_saved_context(convo, source_feedback, draft):
    """After a successful write, keep receipts + draft, not duplicate bodies.

    Only exact feedback objects registered by this loop may be replaced. Trace,
    source receipts, prior model inputs, opaque provider pairs and disk stay intact.
    This is reference compaction, never a summary or factual certificate.
    """
    if not isinstance(draft, str) or len(draft.encode()) > 32_000:
        return False
    changed = False
    for index, message in enumerate(convo):
        for original, result in source_feedback:
            if message is not original:
                continue
            metadata = {key: result[key] for key in ("url", "source", "returned_chars", "total_chars")
                        if key in result}
            metadata["body_compacted_after_save"] = True
            # A tool record keeps its call binding; the receipt replaces the whole
            # old-format turn (header included), hence _legacy_raw.
            extra = {"_legacy_raw": True} if message.get("role") == "tool" else {}
            convo[index] = {**message, **extra, "content": "PREVIOUS WEB READ RECEIPT:\n" +
                wrap_external(json.dumps(metadata, ensure_ascii=False)) +
                "\nThe body was read earlier and remains in the host trace, but is no longer in this "
                "model context. Reopen the source if needed for new claims. This receipt is not factual verification."}
            changed = True
            break
    if changed:
        note = ("\nDRAFT SUBMITTED TO THE SUCCESSFUL WRITE (not a readback or factual certificate):\n" +
                wrap_external(draft) + "\nUse read_file to verify stored bytes when needed.")
        if convo[-1].get("role") == "tool":
            # Old format appended this after the result trailer; a native call
            # already carries the draft in its arguments (trajectory._legacy_result).
            convo[-1] = {**convo[-1], "_legacy_suffix": convo[-1].get("_legacy_suffix", "") + note}
        else:
            convo[-1] = {**convo[-1], "content": convo[-1]["content"] + note}
    return changed
