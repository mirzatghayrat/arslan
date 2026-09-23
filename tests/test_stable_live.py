"""All model replies are local doubles; no paid calls or profile access."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from arslan.llm.adapter import LLMAdapter
from evals.companion import stable_budget as budget
from evals.companion.stable_live import StableAdapter
from tests import test_stable_budget as budget_tests

isolated = budget_tests.isolated
pricing = budget_tests.pricing


def adapter(preflights, usage=None):
    underlying = LLMAdapter("openai", "fixture-model", base_url="https://api.deepseek.com", report_provider="deepseek")
    underlying.chat = AsyncMock(return_value=SimpleNamespace(content="synthetic answer", tool_calls=[], usage=usage))
    return StableAdapter(underlying, "S2-R1", pricing(), preflights["S2-R1"]), underlying


async def test_reserved_before_call_and_actual_usage_persisted(isolated):
    path, preflights = isolated
    guarded, real = adapter(preflights)
    async def reply(*args, **kwargs):
        assert budget.status()["requests"] == 1
        assert (path.parent / "request-01.input.json").exists()
        return SimpleNamespace(content="synthetic answer", tool_calls=[], usage={"prompt_tokens": 100, "completion_tokens": 20})
    real.chat.side_effect = reply
    assert (await guarded.chat("system", "synthetic input")).content == "synthetic answer"
    assert (path.parent / "request-01.accounted.json").exists()
    assert budget.status()["reserved_usd"] == "0.10"
    real.chat.assert_awaited_once()


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": True, "completion_tokens": 1},
    {"prompt_tokens": 200001, "completion_tokens": 1}, {"prompt_tokens": 1, "completion_tokens": 8193}])
async def test_unknown_or_excessive_usage_halts_before_second_call(isolated, usage):
    path, preflights = isolated
    guarded, real = adapter(preflights, usage)
    with pytest.raises(RuntimeError, match="usage"):
        await guarded.chat("system", "synthetic input")
    assert (path.parent / "request-01.response.json").exists()
    with pytest.raises(RuntimeError, match="halted|unaccounted"):
        await guarded.chat("system", "another input")
    assert budget.status()["requests"] == 1
    real.chat.assert_awaited_once()


async def test_error_is_not_retried_and_message_is_not_logged(isolated):
    path, preflights = isolated
    guarded, real = adapter(preflights)
    real.chat.side_effect = OSError("SYNTHETIC_DO_NOT_LOG")
    with pytest.raises(OSError):
        await guarded.chat("system", "synthetic input")
    assert "SYNTHETIC_DO_NOT_LOG" not in (path.parent / "HALT").read_text()
    assert budget.status()["requests"] == 1
    real.chat.assert_awaited_once()


async def test_stream_uses_one_nonstreaming_call(isolated):
    _, preflights = isolated
    guarded, real = adapter(preflights, {"prompt_tokens": 10, "completion_tokens": 10})
    real.chat_stream = AsyncMock(side_effect=AssertionError("must not use retrying stream"))
    assert [part async for part in guarded.chat_stream("system", "synthetic input")] == ["synthetic answer"]
    real.chat.assert_awaited_once()
    real.chat_stream.assert_not_called()


async def test_cancelled_request_keeps_reservation_and_halts(isolated):
    path, preflights = isolated
    guarded, real = adapter(preflights)
    real.chat.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await guarded.chat("system", "synthetic input")
    assert (path.parent / "HALT").exists()
    assert budget.status()["requests"] == 1


def test_wrong_provider_endpoint_refused(isolated):
    _, preflights = isolated
    underlying = LLMAdapter("openai", "fixture-model", base_url="https://example.invalid", report_provider="deepseek")
    with pytest.raises(RuntimeError, match="identity_mismatch"):
        StableAdapter(underlying, "S2-R1", pricing(), preflights["S2-R1"])


@pytest.mark.parametrize("partial", [False, True])
async def test_process_loss_after_reservation_blocks_next_request(isolated, partial):
    path, preflights = isolated
    budget_tests.reserve(preflights)  # Simulates kill after durable reservation.
    if partial:
        (path.parent / "request-01.accounted.json").write_text('{"request":')
    guarded, real = adapter(preflights, {"prompt_tokens": 10, "completion_tokens": 10})
    with pytest.raises(RuntimeError, match="prior_request_unaccounted"):
        await guarded.chat("system", "synthetic input")
    real.chat.assert_not_called()
    assert (path.parent / "HALT").exists()
    assert budget.status()["requests"] == 1


async def test_existing_inflight_lock_refuses_without_spend(isolated):
    import fcntl
    path, preflights = isolated
    guarded, real = adapter(preflights)
    with (path.parent / "inflight.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="already_inflight"):
            await guarded.chat("system", "synthetic input")
    real.chat.assert_not_called()
    assert budget.status()["requests"] == 0
