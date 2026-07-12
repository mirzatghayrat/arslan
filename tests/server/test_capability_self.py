import inspect

from server.orchestrator import arslan, router


def test_arslan_prompt_has_capability_self_block():
    assert "_CAPABILITY_SELF" in dir(arslan)
    txt = arslan._CAPABILITY_SELF
    assert "web_search" in txt
    assert "GitHub" in txt or "github" in txt
    assert "诚实红线" in txt  # never-claim-can't guard present


def test_router_system_biases_to_answer():
    s = router._SYSTEM
    assert "web_search" in s
    # doer-first cue present
    assert ("DEFAULT" in s) or ("默认" in s) or ("itself" in s)


def test_handle_answer_assembles_capability_self():
    # The answer path builds `system` from stable_prefix + volatile_suffix; assert the
    # capability block is actually spliced into the assembled system. The prompt-cache
    # reorder (spec 2026-07-13) moved the assembly into the pure helper _build_answer_system,
    # so assert on its real output — the capability guard is part of the stable prefix.
    system = arslan._build_answer_system(
        extra_system="", roster="(none)", facts="", summary="", kb_block="")
    assert arslan._CAPABILITY_SELF in system
    assert arslan._CAPABILITY_SELF in system.stable  # it's a byte-stable cacheable guard
    # and the source of truth referenced by the helper:
    assert "_CAPABILITY_SELF" in inspect.getsource(arslan._build_answer_system) or \
        arslan._CAPABILITY_SELF in arslan._ANSWER_STABLE_PREFIX
