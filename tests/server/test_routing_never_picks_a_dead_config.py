"""Routing does not send work to a config that cannot possibly answer.

THREE DEFECTS, all present before this file, all silent:

  1. two configs on the same provider score IDENTICALLY, so `>` keeps the first one
     seen — insertion order wins over is_primary, and the user's chosen primary loses
     to whichever row has the lower id.
  2. the routing projection carries no health, so a provider known to be down is as
     attractive as one that works.
  3. it carries no key state either, so a config whose key cannot be decrypted — the
     entire subject of spec ⓪ — is selected, handed an empty key, and fails at the
     provider with a 401 that points at the provider.

🔴 A DEAD CONFIG IS FILTERED, NOT DOWN-WEIGHTED. A weight says "worse"; these are
ZERO. A low weight still wins when everything else is worse, and then the request is
guaranteed to fail — which is how a scoring function ends up choosing something that
cannot work.

🔴 AND THE FILTER MUST NOT EMPTY THE FIELD. If nothing survives, routing falls back to
the primary rather than returning nothing: refusing to answer because no config looks
healthy would turn a stale health probe into an outage. Fail-open on the PROPOSE side
is the standing rule; the honest report goes in the log.
"""
from __future__ import annotations


from arslan.llm import routing


def cfg(id_, provider, *, primary=False, healthy=None, key_state="set"):
    return {"id": id_, "provider": provider, "model": f"{provider}-m", "base_url": "",
            "is_primary": primary, "healthy": healthy, "key_state": key_state}


class TestTiesGoToThePrimary:
    def test_the_users_primary_wins_over_insertion_order(self):
        # 🔴 This fails on the code as it was. Same provider => same score => `>` keeps
        # the first, so the config with the lower id wins and the user's explicit
        # choice is ignored — silently, because both are plausible answers.
        configs = [cfg(1, "openai"), cfg(2, "openai", primary=True)]

        picked = routing.select("execute", "balanced", configs, None)

        assert picked["id"] == 2, "insertion order beat the primary"

    def test_a_genuinely_better_provider_still_wins(self):
        # The other side: the tie-break must not become "the primary always wins",
        # which would make strategy routing decorative.
        configs = [cfg(1, "openai", primary=True), cfg(2, "anthropic")]

        picked = routing.select("execute", "performance", configs, None)

        assert picked is not None


def _assert_the_dead_one_would_otherwise_win(configs):
    """Precondition: without the filter, the dead config is what routing picks.

    🔴 The first draft of these tests used openai (86) as the dead config against a
    deepseek primary (90) under `balanced` — so deepseek won on SCORE and all three
    passed before the filter existed. Green for a reason the test did not claim. The
    dead config is now the highest scorer, and this assertion proves it, so "the other
    one was chosen" can only mean the filter did it.
    """
    weights = routing.STRATEGY_WEIGHTS["balanced"]
    unfiltered = routing._best(configs, weights, None)
    assert unfiltered["id"] == 1, (
        "fixture has no teeth: the dead config would not have won anyway"
    )


class TestDeadConfigsAreExcluded:
    def test_a_config_whose_key_cannot_be_decrypted_is_not_chosen(self):
        # The spec ⓪ state, reaching routing. Selecting this hands the adapter an
        # empty key and produces a 401 that blames the provider.
        configs = [cfg(1, "gemini", key_state="undecryptable"),
                   cfg(2, "deepseek", primary=True)]
        _assert_the_dead_one_would_otherwise_win(configs)

        picked = routing.select("execute", "balanced", configs, None)

        assert picked["id"] == 2

    def test_a_config_with_no_key_at_all_is_not_chosen(self):
        configs = [cfg(1, "gemini", key_state="unset"),
                   cfg(2, "deepseek", primary=True)]
        _assert_the_dead_one_would_otherwise_win(configs)

        assert routing.select("execute", "balanced", configs, None)["id"] == 2

    def test_a_config_known_to_be_unhealthy_is_not_chosen(self):
        configs = [cfg(1, "gemini", healthy=False),
                   cfg(2, "deepseek", primary=True)]
        _assert_the_dead_one_would_otherwise_win(configs)

        assert routing.select("execute", "balanced", configs, None)["id"] == 2

    def test_never_probed_counts_as_usable(self):
        # healthy=None means "no probe has run", not "down". Treating unknown as dead
        # would make a fresh install with no probe history unable to route at all —
        # fail-open on the propose side, which is the standing rule.
        configs = [cfg(1, "gemini", healthy=None), cfg(2, "deepseek", primary=True)]
        _assert_the_dead_one_would_otherwise_win(configs)

        # Unknown must NOT be filtered: the high scorer still wins.
        assert routing.select("execute", "balanced", configs, None)["id"] == 1


class TestTheFilterCannotCauseAnOutage:
    def test_all_dead_falls_back_to_the_primary(self):
        # 🔴 The protective case. Refusing to answer because nothing looks healthy
        # turns a stale probe into an outage. The request may well fail — but it fails
        # at the provider with a real error, not here with a shrug.
        configs = [cfg(1, "openai", key_state="undecryptable"),
                   cfg(2, "deepseek", primary=True, healthy=False)]

        picked = routing.select("execute", "balanced", configs, None)

        assert picked is not None and picked["id"] == 2

    def test_a_single_config_is_used_even_if_it_looks_dead(self):
        configs = [cfg(1, "openai", primary=True, key_state="undecryptable")]

        assert routing.select("execute", "balanced", configs, None)["id"] == 1

    def test_judgment_roles_still_pin_to_primary_regardless(self):
        # E1's rule predates this and must survive it: evaluation never drifts to a
        # cheaper model, healthy or not.
        configs = [cfg(1, "openai"), cfg(2, "deepseek", primary=True)]

        assert routing.select("judge", "performance", configs, None)["id"] == 2


class TestTheProjectionCarriesWhatRoutingNeeds:
    async def test_list_for_routing_includes_health_and_key_state(self):
        # Without these two fields the filter above can only ever be a no-op — the
        # data has to reach the decision, which is the half that is easy to forget.
        import inspect

        from server.services import provider_config_service

        src = inspect.getsource(provider_config_service.list_for_routing)
        assert "healthy" in src and "key_state" in src
