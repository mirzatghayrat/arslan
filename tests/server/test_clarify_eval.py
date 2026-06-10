"""Opt-in eval: clear requests must NOT trigger clarify; vague ones must.

Skipped unless ARSLAN_LIVE_LLM=1, because it calls the real router LLM. Guards against
the clarify prompt drifting toward asking questions about everything.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ARSLAN_LIVE_LLM") != "1", reason="live-LLM eval; set ARSLAN_LIVE_LLM=1 to run"
)

from server.orchestrator import router  # noqa: E402

CLEAR = [
    "draft 3 xiaohongshu posts about retinol",
    "pull the latest A-share ETF flows",
    "write a product description for our oat milk",
]
VAGUE = [
    "分析互联网数据 写report",
    "help me with marketing",
    "做个分析",
]


@pytest.mark.parametrize("msg", CLEAR)
async def test_clear_requests_do_not_clarify(msg):
    result = await router.route("eval", msg)
    assert result.action != "clarify", f"clear request wrongly clarified: {msg!r}"


@pytest.mark.parametrize("msg", VAGUE)
async def test_vague_requests_clarify(msg):
    result = await router.route("eval", msg)
    assert result.action == "clarify", f"vague request not clarified: {msg!r}"
