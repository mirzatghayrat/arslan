"""Tests for deliverable-verdict leveling signal (Task 7: staged orchestration)."""
from server.services import evolution_service as ev


def test_speed_weight_buckets():
    """Verify speed_weight bucketing: fast (<= 5s), normal (<= 60s), slow (> 60s)."""
    assert ev.speed_weight(2.0) == "fast"
    assert ev.speed_weight(5.0) == "fast"
    assert ev.speed_weight(20.0) == "normal"
    assert ev.speed_weight(60.0) == "normal"
    assert ev.speed_weight(300.0) == "slow"


def test_verdict_signal():
    """Verify accept/discard signals in quality_signal_for."""
    assert ev.quality_signal_for("accept") == 1
    assert ev.quality_signal_for("discard") == -1


def test_record_verdict_passes_speed_and_action(monkeypatch):
    """Verify record_verdict calls record_feedback with speed bucket and action."""
    captured = {}

    def fake_record_feedback(
        spawn_name, *, session_id, user_input, agent_output, user_action, edits
    ):
        captured.update(
            spawn_name=spawn_name,
            user_action=user_action,
            edits=edits,
            session_id=session_id,
            user_input=user_input,
            agent_output=agent_output,
        )

    monkeypatch.setattr(ev, "record_feedback", fake_record_feedback)
    ev.record_verdict(
        "领英智囊",
        session_id="s1",
        user_input="u",
        agent_output="o",
        action="accept",
        elapsed_seconds=2.0,
        edits={"k": "v"},
    )
    assert captured["spawn_name"] == "领英智囊"
    assert captured["user_action"] == "accept"
    assert captured["session_id"] == "s1"
    assert captured["user_input"] == "u"
    assert captured["agent_output"] == "o"
    assert captured["edits"]["speed"] == "fast"
    assert captured["edits"]["k"] == "v"


def test_record_verdict_no_edits(monkeypatch):
    """Verify record_verdict works with no extra edits (only speed)."""
    captured = {}

    def fake_record_feedback(
        spawn_name, *, session_id, user_input, agent_output, user_action, edits
    ):
        captured.update(edits=edits)

    monkeypatch.setattr(ev, "record_feedback", fake_record_feedback)
    ev.record_verdict(
        "test_spawn",
        session_id="s1",
        user_input="u",
        agent_output="o",
        action="discard",
        elapsed_seconds=120.0,
    )
    assert captured["edits"]["speed"] == "slow"
    assert len(captured["edits"]) == 1  # Only speed key


def test_record_verdict_speed_is_authoritative(monkeypatch):
    """A caller-supplied 'speed' edit must NOT clobber the computed speed bucket."""
    captured = {}

    def fake_record_feedback(
        spawn_name, *, session_id, user_input, agent_output, user_action, edits
    ):
        captured.update(edits=edits)

    monkeypatch.setattr(ev, "record_feedback", fake_record_feedback)
    ev.record_verdict(
        "test_spawn",
        session_id="s1",
        user_input="u",
        agent_output="o",
        action="accept",
        elapsed_seconds=2.0,
        edits={"speed": "bogus", "k": "v"},
    )
    assert captured["edits"]["speed"] == "fast"  # computed wins
    assert captured["edits"]["k"] == "v"
