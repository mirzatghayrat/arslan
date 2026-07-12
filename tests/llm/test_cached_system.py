"""CachedSystem: stable/volatile split carried through a str subclass.

The prompt-cache reorder (spec 2026-07-13) hinges on this type: it IS a plain str
(so DeepSeek/OpenAI/Ollama and every string consumer see the full reordered prompt
transparently), while carrying the stable/volatile SPLIT so the Anthropic adapter can
emit a cache_control content-block array (stable cached, volatile un-cached).
"""
from arslan.llm.cached_system import CachedSystem, build_cached_system


def test_value_is_stable_then_volatile_byte_exact():
    cs = build_cached_system("STABLE", "\n\nVOLATILE")
    # No injected separator — the value is exactly the direct concatenation, so it is
    # byte-identical to what the old `stable + volatile` assembly produced.
    assert str(cs) == "STABLE\n\nVOLATILE"
    assert cs.stable == "STABLE"
    assert cs.volatile == "\n\nVOLATILE"


def test_is_a_real_str():
    cs = build_cached_system("A", "B")
    assert isinstance(cs, str)
    assert cs == "AB"
    assert cs.startswith("A") and cs.endswith("B")


def test_empty_volatile_value_is_exactly_stable():
    # Router case: dynamic content lives in the user message, so volatile == "".
    cs = build_cached_system("RUBRIC", "")
    assert str(cs) == "RUBRIC"
    assert cs.stable == "RUBRIC"
    assert cs.volatile == ""


def test_concatenation_appends_to_volatile_and_preserves_split():
    # tool_loop.run_native does `system = system + _NATIVE_EFFICIENCY + "\n\n" + GUARD`.
    # Those trailing STATIC guards must land in the volatile block (uncached) so the
    # stable prefix stays byte-identical across turns.
    cs = build_cached_system("STABLE", "VOL")
    grown = cs + "X" + "Y"
    assert isinstance(grown, CachedSystem)
    assert grown.stable == "STABLE"          # unchanged — the cached prefix is frozen
    assert grown.volatile == "VOLXY"
    assert str(grown) == "STABLEVOLXY"


def test_plain_str_on_left_degrades_to_plain_str():
    # `"prefix" + cached` is not in any hot path; it must not silently mis-split.
    cs = build_cached_system("S", "V")
    out = "P" + cs
    assert out == "PSV"
    assert not isinstance(out, CachedSystem)  # plain str → Anthropic gets no cache block


def test_stable_is_byte_stable_across_different_volatiles():
    # The regression this whole change exists to prevent: nail that the cacheable prefix
    # never varies with per-turn content.
    a = build_cached_system("GUARDS", "roster=1 clock=10:00")
    b = build_cached_system("GUARDS", "roster=2 clock=23:59 facts=...")
    assert a.stable == b.stable
    assert a.volatile != b.volatile
