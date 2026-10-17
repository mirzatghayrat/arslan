"""S3-M1 Task 3: the WS layer keeps a Run's cancel handle on stream_start.

0.1.63 (C1): the expert-dispatch cancel tests that lived here were deleted with
_dispatch_spawn; an Arslan turn's cancel is covered by the task tests."""

from server.ws import arslan as ws_arslan


def test_to_frame_keeps_run_id_on_stream_start():
    """The WS layer REBUILDS stream_start frames — without passing run_id through,
    the client would never receive its cancel handle (silent-drop regression pin)."""
    frame = ws_arslan._to_frame(
        {"type": "stream_start", "source": "spawn", "spawn_id": 3, "run_id": 42})
    assert frame["run_id"] == 42
    bare = ws_arslan._to_frame({"type": "stream_start", "source": "arslan"})
    assert "run_id" not in bare
