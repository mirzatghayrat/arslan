"""C8-1 (v0.1.63): what the model sees after a saved report is byte-for-byte what it saw before
`compact_saved_context` moved out of `research_review`.

The C8 card deletes research review, but `compact_saved_context` is not review: on every
provider that does not clear old tool results itself (all but Claude's native path), a saved
report swaps the earlier web-page bodies for receipts. Change it and DeepSeek sees something
else, so it moves without a single changed character, and this test pins the result.

`golden/saved_context_after_save.json` is the full message list of the request that follows the
save, captured on the code BEFORE the move (main 26b4e603) through the real `tool_loop.run_native`
turn: two `web_extract` reads, then `write_file notes.md`, then the answer. The same turn on the
moved code must produce identical bytes. Regenerate only on purpose, with
`ARSLAN_REGEN_SAVED_CONTEXT_GOLDEN=1`, and say why in the PR.
"""
import json
import os
from pathlib import Path

import pytest

from tests.server import test_k3b_sent_is_final as k3b

GOLDEN = Path(__file__).parent / "golden" / "saved_context_after_save.json"


def _canonical(messages) -> str:
    return json.dumps(messages, ensure_ascii=False, indent=1, sort_keys=True, default=repr) + "\n"


@pytest.mark.asyncio
async def test_the_context_after_a_saved_report_is_unchanged_byte_for_byte(monkeypatch):
    *_, after_save = await k3b._run(monkeypatch, trims=False)
    got = _canonical(after_save)
    if os.environ.get("ARSLAN_REGEN_SAVED_CONTEXT_GOLDEN") == "1":
        GOLDEN.write_text(got, encoding="utf-8")
    # The snapshot is of a context the compaction really changed — not of a no-op.
    assert got.count("PREVIOUS WEB READ RECEIPT") == 2
    assert "DRAFT SUBMITTED TO THE SUCCESSFUL WRITE" in got
    assert got == GOLDEN.read_text(encoding="utf-8")
