"""Hands v2 §4.4: when the model refuses a screenshot AS AN IMAGE (vision_errors' narrow match),
the turn's screenshots become the text this Mac reads off them, framed as untrusted, and that
model call is repeated once; the model configuration is remembered, so later screenshots are
read before sending. A rate limit or any other failure never starts that. No model is called:
the adapter is a stand-in and the recogniser is faked."""
import json
from types import SimpleNamespace

import pytest

from arslan.llm import trajectory as tj
from server.orchestrator import model_call as mc
from server.orchestrator import tool_loop
from server.services import ocr_fallback

REFUSAL = "400 Bad Request: this model does not support image input"
SHOT = {"mime_type": "image/jpeg", "data": "aGVsbG8="}       # base64 of b"hello"


class Adapter:
    def __init__(self, failures):
        self.failures, self.sent = list(failures), []
        self._provider = SimpleNamespace(model="small-model", base_url="https://example.invalid/v1")

    async def chat(self, system, content, history=None, tools=None, **kw):
        self.sent.append([*(history or []), {"role": "user", "content": content}])
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(content="ok", tool_calls=[], finish_reason="stop", continuation=None)


@pytest.fixture(autouse=True)
def faked(monkeypatch):
    tool_loop._REFUSES_IMAGES.clear()
    read = []

    def read_locally(data, *, ui_language, chosen_languages=None):
        read.append(data)
        return "Save  Delete  Title", "ok"

    async def none():
        return None

    async def passthrough(request, state, remaining_s=None):
        try:
            return await request()
        except mc.ModelCallError:
            raise
        except RuntimeError as exc:
            raise mc.ModelCallError("protocol", status=400, excerpt=str(exc), attempts=1, waited_s=0,
                                    recoveries=[]) from exc
    monkeypatch.setattr(ocr_fallback, "read_locally", read_locally)
    monkeypatch.setattr(ocr_fallback, "current_ui_language", none)
    monkeypatch.setattr(ocr_fallback, "current_ocr_languages", none)
    monkeypatch.setattr(mc, "call_with_recovery", passthrough)
    yield read
    tool_loop._REFUSES_IMAGES.clear()


def turn():
    return [tj.tool_result(None, "desktop_look", "Notes — window “Groceries”", synthetic=True,
                           legacy_call="look", images=[SHOT], image_label="Notes · Groceries")]


async def call(adapter, convo, state=None):
    return await tool_loop._model_call(adapter, "s", convo, {"role": "user", "content": "do it"}, tools=None,
                                       schemas=None, forced=False, state=state or mc.TurnRecovery())


def images_in(messages) -> bool:
    return "aGVsbG8=" in json.dumps(messages)


async def test_a_refused_screenshot_is_read_locally_and_the_call_repeated_once(faked):
    adapter = Adapter([RuntimeError(REFUSAL)])
    convo = turn()
    state = mc.TurnRecovery()
    resp = await call(adapter, convo, state)
    assert resp.content == "ok"
    assert images_in(adapter.sent[0]) and not images_in(adapter.sent[1])
    last = adapter.sent[1][-1]["content"]               # the look's result turn
    assert "Save  Delete  Title" in last and "this model cannot take images" in last
    assert tool_loop.wrap_external("Save  Delete  Title") in last      # framed: it is window content
    assert faked == [b"hello"]
    assert state.images_read_locally and "read screenshots as text" in " ".join(state.recoveries)


async def test_the_model_is_remembered_so_the_next_screenshot_is_read_before_sending(faked):
    await call(Adapter([RuntimeError(REFUSAL)]), turn())
    again = Adapter([])
    await call(again, turn())
    assert len(again.sent) == 1 and not images_in(again.sent[0])
    other = Adapter([])
    other._provider = SimpleNamespace(model="vision-model", base_url="https://example.invalid/v1")
    await call(other, turn())
    assert images_in(other.sent[0])                      # a different model still gets the image


async def test_a_failure_that_is_not_about_images_never_reads_them(faked):
    adapter = Adapter([RuntimeError("429 rate limit exceeded")])
    with pytest.raises(mc.ModelCallError):
        await call(adapter, turn())
    assert faked == [] and not tool_loop._REFUSES_IMAGES


async def test_only_one_local_reading_per_turn(faked):
    adapter = Adapter([RuntimeError(REFUSAL), RuntimeError(REFUSAL)])
    with pytest.raises(mc.ModelCallError):
        await call(adapter, turn())
    assert len(adapter.sent) == 2


class NativeAdapter(Adapter):
    """An OpenAI-compatible endpoint: the native protocol first, where an image refusal comes
    back as a 400 that also looks like a protocol rejection."""

    def native_trajectory(self):
        return True

    async def chat_trajectory(self, system, messages, tools=None, tool_choice=None, **kw):
        self.sent.append(list(messages))
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(content="ok", tool_calls=[], finish_reason="stop", continuation=None)


async def test_on_the_native_protocol_an_image_refusal_is_read_not_resent_in_another_protocol(faked):
    adapter = NativeAdapter([RuntimeError(REFUSAL)])
    resp = await call(adapter, turn())
    assert resp.content == "ok"
    assert len(adapter.sent) == 2 and not images_in(adapter.sent[1])
