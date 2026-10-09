"""Hands v2 screenshots in tool results (spec 2026-10-08-0157 §4.3–4.5): an image reaches the
model as an image part of its result on every provider path, and nowhere else — not the
payload text, the trace, the run trace, the UI event. Only the newest two stay images; an
image counts for a fixed size when the history is measured, not for its base64 length.
Payloads are built and read here; nothing is sent to any model."""
import json

from arslan.llm import trajectory as tj
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from arslan.llm.providers.openai_provider import OpenAIProvider
from server.orchestrator import tool_loop

PIXELS = "QUJDREVGR0g" * 40        # stands in for a screenshot's base64; unique in every payload
SHOT = {"mime_type": "image/jpeg", "data": PIXELS}


def look_result(text="Notes — window “Groceries”", images=(SHOT,)):
    return {"ok": True, "external": True, "text": text, "summary": "look · Notes",
            "images": list(images), "image_label": "Notes · Groceries"}


def record(result, convo, events=None, trace=None):
    return tool_loop._record_tool_result("desktop_look", {"app": "Notes"}, result,
                                         (events if events is not None else []).append,
                                         trace if trace is not None else [], "look at Notes", convo)


def test_the_image_goes_to_the_trajectory_and_nowhere_else(monkeypatch):
    recorded = []
    monkeypatch.setattr(tool_loop.run_trace, "record", lambda **kw: recorded.append(kw))
    convo, events, trace = [], [], []
    returned = record(look_result(), convo, events, trace)
    assert convo[-1]["_images"] == [{"type": "image", **SHOT}]
    assert convo[-1]["_image_label"] == "Notes · Groceries"
    assert PIXELS not in convo[-1]["content"]
    for elsewhere in (returned, events, trace, recorded):
        assert PIXELS not in json.dumps(elsewhere, ensure_ascii=False, default=str), elsewhere


def test_legacy_rendering_puts_the_image_in_the_results_own_turn():
    convo = []
    record(look_result(), convo)
    rendered = tj.to_legacy(convo)
    content = rendered[-1]["content"]
    assert rendered[-1]["role"] == "user" and isinstance(content, list)
    assert content[0]["type"] == "text" and content[0]["text"].startswith("TOOL RESULT for desktop_look")
    assert content[1] == {"type": "image", **SHOT}
    # Measuring never sees the pixels: a one-line stub instead.
    measured = tj.to_legacy(convo, images=False)[-1]["content"]
    assert isinstance(measured, str) and "[screenshot of Notes · Groceries]" in measured
    assert PIXELS not in measured


def test_anthropic_and_gemini_payloads_carry_the_image_as_an_image():
    convo = []
    record(look_result(), convo)
    rendered = tj.to_legacy(convo)
    wire = [{"role": "system", "content": "s"}, *rendered]
    anthropic = AnthropicProvider(model="claude-test", api_key="x")._payload(wire, 0.0)
    blocks = anthropic["messages"][-1]["content"]
    assert blocks[1] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": PIXELS}}
    gemini = GeminiProvider(model="gemini-test", api_key="x")._payload(wire, 0.0)
    parts = gemini["contents"][-1]["parts"]
    assert {"inline_data": {"mime_type": "image/jpeg", "data": PIXELS}} in parts
    assert not any(PIXELS in p.get("text", "") for p in parts)


def test_gemini_function_response_turn_carries_the_screenshot_after_the_responses():
    call = {"id": "c1", "name": "desktop_look", "arguments": {"app": "Notes"}, "arguments_raw": "{}",
            "provider_id": "g1"}
    head = tj.assistant(None, [call], continuation={"protocol": "gemini",
                                                    "provider_content": {"provider": "gemini", "parts": []}})
    result = tj.tool_result("c1", "desktop_look", "the tree", images=[SHOT], image_label="Notes · Groceries")
    rendered = tj.to_legacy([head, result])
    content = rendered[-1]["content"]
    assert content[0]["type"] == "function_response"
    assert content[-1] == {"type": "image", **SHOT}
    assert PIXELS not in json.dumps(content[0])


def test_native_openai_sends_the_screenshot_as_a_user_message_after_the_steps_tool_messages():
    calls = [{"id": "a", "name": "desktop_look", "arguments": {}, "arguments_raw": "{}"},
             {"id": "b", "name": "desktop_apps", "arguments": {}, "arguments_raw": "{}"}]
    messages = [{"role": "user", "content": "do it"}, tj.assistant(None, calls),
                tj.tool_result("a", "desktop_look", "the tree", images=[SHOT], image_label="Notes · Groceries"),
                tj.tool_result("b", "desktop_apps", "apps"),
                tj.assistant("done")]
    provider = OpenAIProvider(model="gpt-test", api_key="x")
    wire = provider.build_trajectory_messages("s", messages)
    assert [m["role"] for m in wire] == ["system", "user", "assistant", "tool", "tool", "user", "assistant"]
    assert all(isinstance(m["content"], str) for m in wire if m["role"] == "tool")
    shot = wire[5]["content"]
    assert shot[0]["type"] == "text" and "desktop_look (call a)" in shot[0]["text"]
    assert shot[1] == {"type": "image", **SHOT}
    body = provider._payload(wire, None, 0.0)
    assert body["messages"][5]["content"][1] == {"type": "image_url",
                                                "image_url": {"url": f"data:image/jpeg;base64,{PIXELS}"}}
    assert all(not k.startswith("_") for m in wire for k in m)


def test_only_the_newest_two_screenshots_stay_images():
    convo = []
    for n in range(3):
        record(look_result(text=f"look {n}", images=[{"mime_type": "image/jpeg", "data": f"{PIXELS}{n}"}]),
               convo)
    assert [bool(m.get("_images")) for m in convo] == [False, True, True]
    assert convo[0]["content"].endswith("[screenshot of Notes · Groceries: no longer shown]")
    assert f"{PIXELS}0" not in json.dumps(tj.to_legacy(convo))


def test_an_image_is_measured_as_a_fixed_size_not_its_base64():
    plain, shot = [], []
    record(look_result(images=()), plain)
    record(look_result(images=[{"mime_type": "image/jpeg", "data": "A" * 500_000}]), shot)
    grown = tool_loop._rendered_size(shot) - tool_loop._rendered_size(plain)
    assert 0 < grown < tj.IMAGE_SIZE_CHARS + 200


def test_an_omitted_result_loses_its_image_too():
    calls = [{"id": "a", "name": "desktop_look", "arguments": {}, "arguments_raw": "{}"}]
    group = [tj.assistant(None, calls), tj.tool_result("a", "desktop_look", "x" * 5_000, images=[SHOT])]
    shrunk = tj.shrink_group(group, 100, lambda g: len(json.dumps(tj.to_legacy(g, images=False))))
    assert shrunk[1]["content"] == tj.OMITTED_RESULT and "_images" not in shrunk[1]
