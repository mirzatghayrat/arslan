from server.orchestrator import dispatcher

def test_propose_framing_present():
    brief = dispatcher._frame_brief("optimize headline", mode="propose")
    assert "propose" in brief.lower()
    assert "do not produce the final deliverable" in brief.lower()
    assert "optimize headline" in brief

def test_execute_framing_is_plain():
    assert dispatcher._frame_brief("optimize headline", mode="execute") == "optimize headline"

def test_default_mode_is_execute():
    assert dispatcher._frame_brief("x") == "x"

def test_execute_confirmed_framing_instructs_delivery_and_carries_direction():
    brief = dispatcher._frame_brief(
        "optimize headline", mode="execute_confirmed",
        proposed_direction="punchy data-driven angle",
    )
    low = brief.lower()
    assert "confirmed" in low
    assert "deliver" in low                       # tells the spawn to produce the deliverable
    assert "do not" in low                        # ...and not re-ask / re-propose
    assert "optimize headline" in brief           # the task
    assert "punchy data-driven angle" in brief    # the spawn's proposed direction, carried forward
    assert "propose mode" not in low

def test_execute_confirmed_without_direction_still_frames():
    brief = dispatcher._frame_brief("do X", mode="execute_confirmed")
    assert "confirmed" in brief.lower()
    assert "do X" in brief
