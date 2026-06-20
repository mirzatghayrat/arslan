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
