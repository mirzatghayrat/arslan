# tests/server/test_eval_sealing.py
from server.services import replay_safety
from server.services.replay_run import REPLAY_CONVERSATION_ID


def test_is_hermetic_context_matches_both_eval_sentinels():
    # Both eval sentinels are hermetic; a real conversation id and None are not.
    assert replay_safety.is_hermetic_context("evolution-eval") is True
    assert replay_safety.is_hermetic_context("evolution-replay") is True
    assert replay_safety.is_hermetic_context(REPLAY_CONVERSATION_ID) is True  # == "evolution-replay"
    assert replay_safety.is_hermetic_context("conv_abc123") is False
    assert replay_safety.is_hermetic_context(None) is False


def test_hermetic_set_covers_the_evaluator_sentinel_literal():
    # evaluator.py + evolution_loop._val_outputs dispatch under "evolution-eval";
    # pin that literal is a member so a rename can't silently un-seal them.
    assert "evolution-eval" in replay_safety._HERMETIC_CONVERSATION_IDS
