"""0.1.49 S2: neutral trajectory invariants and the legacy renderer."""
import pytest

from arslan.llm import trajectory as tj


def _call(cid, name="web_search", args=None):
    return {"id": cid, "name": name, "arguments": args or {}, "arguments_raw": "{}"}


def _turn():
    return [
        {"role": "user", "content": "task"},
        tj.assistant("thinking aloud", [_call("a"), _call("b", "read_file")],
                     continuation={"protocol": "openai", "endpoint": "e", "fields": {"reasoning_content": "r"}}),
        tj.tool_result("a", "web_search", "<<<X>>>found<<<END>>>"),
        tj.tool_result("b", "read_file", "missing path"),
        tj.assistant("final"),
    ]


def test_valid_turn_passes():
    tj.validate(_turn())


@pytest.mark.parametrize("mutate", [
    lambda t: t.pop(3),                                   # a call left unanswered
    lambda t: t.insert(1, tj.tool_result("z", "x", "c")),  # orphan result
    lambda t: t.__setitem__(slice(2, 4), [t[3], t[2]]),    # answered out of order
    lambda t: t[1]["tool_calls"].__setitem__(1, _call("a")),  # duplicate id
    lambda t: t.insert(3, {"role": "user", "content": "interleaved"}),
])
def test_invariant_violations_are_rejected(mutate):
    turn = _turn()
    mutate(turn)
    with pytest.raises(tj.TrajectoryError):
        tj.validate(turn)


def test_synthetic_results_stand_alone():
    tj.validate([{"role": "user", "content": "t"},
                 tj.tool_result("pre_0", "web_search", "x", synthetic=True, legacy_call="{}")])


def test_groups_never_split_a_call_from_its_results():
    sizes = [len(g) for g in tj.groups(_turn())]
    assert sizes == [1, 3, 1]


def test_legacy_rendering_is_the_old_text_protocol():
    out = tj.to_legacy(_turn())
    assert out == [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "Native tool invocation completed: web_search"},
        {"role": "user", "content": "TOOL RESULT for web_search:\n<<<X>>>found<<<END>>>" + tj.LEGACY_TRAILER},
        {"role": "assistant", "content": "Native tool invocation completed: read_file"},
        {"role": "user", "content": "TOOL RESULT for read_file:\nmissing path" + tj.LEGACY_TRAILER},
        {"role": "assistant", "content": "final"},
    ]
    assert "thinking aloud" not in str(out) and "reasoning_content" not in str(out)


def test_legacy_synthetic_keeps_original_invocation_text():
    raw = '{"tool": "web_search", "args": {"query": "é"}}'
    out = tj.to_legacy([tj.tool_result("p", "web_search", "res", synthetic=True, legacy_call=raw)])
    assert out[0] == {"role": "assistant", "content": raw}


def test_legacy_gemini_group_becomes_provider_pair():
    pc = {"provider": "gemini", "parts": [{"functionCall": {"id": "fc", "name": "web_search", "args": {}}}]}
    msgs = [tj.assistant("n", [{**_call("g0"), "provider_id": "fc"}],
                         continuation={"protocol": "gemini", "provider_content": pc}),
            tj.tool_result("g0", "web_search", "res")]
    out = tj.to_legacy(msgs)
    assert out[0] == {"role": "assistant", "content": [{"type": "provider_content", **pc}]}
    assert out[1] == {"role": "user", "content": [{"type": "function_response", "name": "web_search", "id": "fc",
                                                   "response": {"result": "TOOL RESULT for web_search:\nres"
                                                                + tj.LEGACY_TRAILER}}]}


def test_unique_ids_repairs_empty_and_repeated():
    seen = {"call_0"}
    calls = tj.unique_ids([_call(""), _call("call_0"), _call("ok")], seen, step=3)
    assert [c["id"] for c in calls] == ["call_3_0", "call_3_1", "ok"]


def test_call_from_response_keeps_raw_and_marks_unparsed():
    c = tj.call_from_response({"id": "", "function": {"name": "write_file", "arguments": '{"path": "a'},
                               "arguments_raw": '{"path": "a'}, "fb")
    assert c == {"id": "fb", "name": "write_file", "arguments": None, "arguments_raw": '{"path": "a'}


def test_a_synthetic_result_after_a_group_is_its_own_unit():
    turn = _turn()[:4] + [tj.tool_result("p", "web_search", "x", synthetic=True, legacy_call="{}")]
    assert [len(g) for g in tj.groups(turn)] == [1, 3, 1]
