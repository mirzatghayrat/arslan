"""turn_journal — the orchestrator answer turn's reattach seam.

Spawn runs already survive a thread switch: RunRecorder journals every frame
and the WS attach block replays them behind run_in_progress. Arslan's OWN
answer/tool turn had no journal, so switching threads and back showed a blank
pane while the turn kept running — the reattached sink delivered its frames,
but the client, never having seen a stream_start on this socket, discarded
them (arslanStore's `if (!streaming) break` guards). The journal is that
missing preamble.

Contract pinned here:
- tee() passes EVERY event through to the wrapped emit, but journals only the
  answer-turn frame vocabulary — spawn-run frames flowing through the same
  emit (dispatch inherits the caller's emit) are already journaled by their
  RunRecorder, and double-journaling would mean double replay.
- snapshot() is a copy, only while the turn is in flight; end() pops only its
  own journal (a racing begin from another tab must not be clobbered).
"""
import server.orchestrator.arslan as arslan_mod
from server.services import turn_journal


def _drain_active():
    turn_journal._active.clear()


def setup_function(_fn):
    _drain_active()


def teardown_function(_fn):
    _drain_active()


def test_tee_passes_everything_through_but_journals_only_turn_frames():
    seen = []
    j = turn_journal.begin("c1")
    tee = j.tee(seen.append)
    turn = {"type": "stream_start", "source": "arslan"}
    spawn_frame = {"type": "run_started", "run_id": 5}
    tee(turn)
    tee(spawn_frame)
    assert seen == [turn, spawn_frame]                       # emit sees everything
    assert turn_journal.snapshot("c1") == [turn]             # journal: whitelist only


def test_whitelist_covers_the_answer_turn_vocabulary():
    j = turn_journal.begin("c2")
    tee = j.tee(lambda ev: None)
    events = [
        {"type": "stream_start", "source": "arslan"},
        {"type": "stream_chunk", "content": "partial"},
        {"type": "tool_call", "tool": "web_search", "args_summary": "q"},
        {"type": "tool_result", "tool": "web_search", "ok": True, "summary": "s"},
        {"type": "note", "text": "n"},
        {"type": "stream_end", "message_id": 3},
    ]
    for ev in events:
        tee(ev)
    assert turn_journal.snapshot("c2") == events


def test_snapshot_is_a_copy_and_empty_after_end():
    j = turn_journal.begin("c3")
    j.tee(lambda ev: None)({"type": "stream_chunk", "content": "x"})
    snap = turn_journal.snapshot("c3")
    snap.append({"type": "bogus"})                           # mutating the copy
    assert len(turn_journal.snapshot("c3")) == 1             # ...doesn't touch the journal
    turn_journal.end("c3", j)
    assert turn_journal.snapshot("c3") == []
    assert not turn_journal.active("c3")


def test_end_pops_only_its_own_journal():
    j1 = turn_journal.begin("c4")
    j2 = turn_journal.begin("c4")                            # second tab's turn overwrites
    turn_journal.end("c4", j1)                               # stale end must not clobber j2
    assert turn_journal.active("c4")
    turn_journal.end("c4", j2)
    assert not turn_journal.active("c4")


async def test_handle_answer_journals_while_running_and_clears_after(monkeypatch):
    """Placement: the tee wraps _handle_answer's whole body — events emitted by
    the body are snapshot-able mid-flight (that IS the reattach window), and the
    journal is gone once the turn returns, success or raise."""
    captured = {}

    async def fake_body(conversation_id, user_message, emit, **kwargs):  # noqa: ANN001
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_chunk", "content": "partial"})
        captured["mid_flight"] = turn_journal.snapshot(conversation_id)
        return "done"

    monkeypatch.setattr(arslan_mod, "_handle_answer_body", fake_body)
    out = await arslan_mod._handle_answer("conv-a", "hi", lambda ev: None)
    assert out == "done"
    assert [e["type"] for e in captured["mid_flight"]] == ["stream_start", "stream_chunk"]
    assert not turn_journal.active("conv-a")                 # cleared on the way out

    async def raising_body(conversation_id, user_message, emit, **kwargs):  # noqa: ANN001
        emit({"type": "stream_start", "source": "arslan"})
        raise RuntimeError("boom")

    monkeypatch.setattr(arslan_mod, "_handle_answer_body", raising_body)
    try:
        await arslan_mod._handle_answer("conv-a", "hi", lambda ev: None)
    except RuntimeError:
        pass
    assert not turn_journal.active("conv-a")                 # cleared on raise too
