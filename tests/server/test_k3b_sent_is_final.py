"""K3b: on Claude's native path, what was sent is never edited again, not even to compact saved web reads.

K3's Claude run (T2 r1): after a background job saved progress_notes.md, `research_review.compact_saved_context`
swapped three earlier `web_extract` bodies for receipts. An edit in the middle of the history sends the prompt
cache back to the system prompt (a prefix is looked up only at the breakpoints), and that request rewrote 45k
tokens. On that path the server clears old tool results itself (K1b's `_SENT_IS_FINAL`), so the compaction only
cost money. Other providers keep it.
"""
from types import SimpleNamespace

import pytest

from server.orchestrator import tool_loop
from tests.server import test_agent_status_requests as status_requests
from tests.server import test_trajectory_golden as golden

RECEIPT = "PREVIOUS WEB READ RECEIPT"
BODY = "Body of https://example.test/a"


def _turn():
    return [status_requests.Resp(None, [golden._tc("web_extract", {"url": "https://example.test/a"}, "c1"),
                                        golden._tc("web_extract", {"url": "https://example.test/b"}, "c2")]),
            status_requests.Resp(None, [golden._tc("write_file", {"path": "notes.md", "content": "# Notes"}, "c3")]),
            status_requests.Resp("Saved notes.md.")]


class Native(status_requests.NativeRecorder):
    def __init__(self, replies, *, trims):
        super().__init__(replies)
        self._provider = SimpleNamespace(trims_context_server_side=lambda: trims)


async def _run(monkeypatch, *, trims):
    adapter = Native(_turn(), trims=trims)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)

    async def own():
        return True
    monkeypatch.setattr(tool_loop, "_writing_in_own_folder", own)
    from server.registry import executors
    for key, executor in {"web_extract": golden._Extract, "write_file": golden._Write}.items():
        monkeypatch.setitem(executors.EXECUTORS, key, executor())
    result = await tool_loop.run_native(system="SYS", user_content="research then save", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None,
                                        resolve_tools=status_requests._resolve)
    assert result["final"] == "Saved notes.md." and len(adapter.calls) == 3
    return [call["messages"] for call in adapter.calls]


@pytest.mark.asyncio
async def test_on_a_provider_that_clears_old_results_itself_a_save_never_edits_what_was_sent(monkeypatch):
    first, second, after_save = await _run(monkeypatch, trims=True)
    assert RECEIPT not in str(after_save) and BODY in str(after_save)
    # Append-only: everything before the last message is the previous request's bytes (its last message
    # differs only by its status tail, see test_agent_status_requests).
    assert after_save[:len(second) - 1] == second[:-1]


@pytest.mark.asyncio
async def test_elsewhere_a_save_still_compacts_the_web_reads_it_used(monkeypatch):
    *_, after_save = await _run(monkeypatch, trims=False)
    assert RECEIPT in str(after_save)
