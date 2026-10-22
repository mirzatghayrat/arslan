"""A model call that never pauses is still cut by the turn's time, and still stops when the turn is stopped.

Python 3.11's asyncio.wait_for returns what it awaited and drops a cancellation that lands just as that
completes (gh-86296). A stream that keeps sending completes an awaited line on nearly every loop turn, so
the turn's cut (or a stop) could be lost and the call run forever: seen as a 120 s hang of K8b's ping test
under load. The three assemblers' idle bounds and model_call's per-call limit use asyncio.timeout, which
counts cancellations, so neither is lost.
"""
import asyncio
import json

import httpx
import pytest

from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from arslan.llm.providers.openai_provider import OpenAIProvider
from server.orchestrator import model_call
from tests.llm.test_k8b_anthropic_stream import event, start
from tests.llm.test_k8c_gemini_stream import chunk

_DELTA = ("data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk", "model": "deepseek-chat",
                                 "choices": [{"index": 0, "delta": {"content": "a"}}]}) + "\n\n").encode()


class _Endless(httpx.AsyncByteStream):
    """Sends `first`, then `each` on every loop turn, forever."""

    def __init__(self, first: bytes, each: bytes, sent: list):
        self.first, self.each, self.sent = first, each, sent

    async def __aiter__(self):
        yield self.first
        while True:
            await asyncio.sleep(0)
            self.sent.append(1)
            yield self.each


def _provider(name: str, sent: list):
    def transport(first, each):
        return httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=_Endless(first, each, sent)))
    if name == "anthropic":
        return AnthropicProvider("claude-opus-5-5", api_key="k", base_url="https://api.anthropic.com/v1",
                                 transport=transport(start().encode(), event("ping").encode()))
    if name == "gemini":
        return GeminiProvider("gemini-3-pro", api_key="k", base_url="https://generativelanguage.googleapis.com/v1beta",
                              transport=transport(chunk({"text": "a"}).encode(), chunk({"text": ""}).encode()))
    return OpenAIProvider(model="deepseek-chat", api_key="k", base_url="https://api.deepseek.com/v1",
                          transport=transport(_DELTA, _DELTA))


@pytest.mark.timeout(20, method="thread")      # a lost cancel can swallow the signal too
@pytest.mark.parametrize("name", ["anthropic", "gemini", "openai"])
async def test_a_stream_that_never_pauses_is_cut_by_the_turns_time(name):
    provider = _provider(name, [])
    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(model_call.ModelCallError):
        await model_call.call_with_recovery(
            lambda: provider.chat([{"role": "user", "content": "hi"}], stream=True), model_call.TurnRecovery(),
            remaining_s=lambda: 0.5)
    assert loop.time() - started < 5            # the 1 s floor on a call, not the 300 s idle bound


@pytest.mark.timeout(20, method="thread")      # a lost cancel can swallow the signal too
@pytest.mark.parametrize("name", ["anthropic", "gemini", "openai"])
async def test_stopping_the_turn_stops_a_stream_that_never_pauses(name):
    sent: list = []
    provider = _provider(name, sent)
    call = asyncio.create_task(model_call.call_with_recovery(
        lambda: provider.chat([{"role": "user", "content": "hi"}], stream=True), model_call.TurnRecovery(),
        remaining_s=lambda: 60))
    while len(sent) < 50:
        await asyncio.sleep(0.001)
    loop = asyncio.get_running_loop()
    stopped = loop.time()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):          # a stop, never reported as a timeout
        await call
    assert loop.time() - stopped < 3


@pytest.mark.timeout(20, method="thread")      # a lost cancel can swallow the signal too
async def test_a_stop_that_lands_as_the_answer_arrives_is_not_lost():
    """The stop and the model's answer in the same loop turn: the stop wins (wait_for returned the answer)."""
    loop = asyncio.get_running_loop()
    answer = loop.create_future()
    call = asyncio.create_task(model_call.call_with_recovery(lambda: answer, model_call.TurnRecovery(),
                                                             remaining_s=lambda: 60))
    await asyncio.sleep(0)                          # the call is waiting for the answer
    loop.call_soon(answer.set_result, "answer")
    loop.call_soon(call.cancel)
    with pytest.raises(asyncio.CancelledError):
        await call


def test_the_expiry_is_the_same_timeout_error_callers_catch():
    assert asyncio.TimeoutError is TimeoutError
