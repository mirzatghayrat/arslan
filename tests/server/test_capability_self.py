import inspect

from server.orchestrator import arslan


def test_arslan_prompt_says_how_it_really_works():
    """0.1.48: the self-description matches the real toolset — the terminal is the
    general hand, deliverables are files in Arslan's folder, act now, try another route
    — and it no longer claims Arslan cannot make files."""
    txt = arslan._CAPABILITY_SELF
    for must in ("run_command", "~/Arslan", "start_background_work", "list_my_capabilities",
                 "never claim a tool you don't have", "Never type passwords"):
        assert must in txt, must
    assert "PPT/PDF" not in txt and "分身" not in txt




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
