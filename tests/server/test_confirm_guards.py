"""Doom-loop guards (from a live incident): a tool-exhaustion refusal self-replicated
through the confirm→execute path for 8+ rounds. Three独立 guards, each tested:
  1. stale confirm (no pending direction) → honest notice, NO dispatch;
  2. a refusal/fallback output is never carried as the "confirmed direction";
  3. a claimed-but-not-generated PPTX triggers the reactive deck guard."""
import pytest

from server.orchestrator import arslan, tool_loop

pytestmark = pytest.mark.asyncio


def test_refusal_detector_matches_live_incident_phrasings():
    for s in [
        "抱歉，我在收集资料时用尽了工具额度，没能整理出完整结论。",
        "这一轮的工具调用次数用完了,还没能整理出完整结论。",
        "这个任务这一轮还没做完。回复“继续”我就接着做。",      # current fallback copy
        "I didn't finish this one in a single round.",
        "I have zero remaining tool quota and cannot produce a deliverable.",
        "I have exhausted my web search and web extraction tool quota for this session.",
        "Understood. I have no remaining tool quota and cannot produce a new deliverable.",
    ]:
        assert arslan._looks_like_refusal(s), s
    for s in [  # real proposals/deliverables must NOT match
        "# OKX 永续合约调研报告\n数据截止日期:2025年7月…",
        "我建议按三步走:1) 币对数量 2) 交易量前十 3) 竞品对比。确认后我就执行。",
    ]:
        assert not arslan._looks_like_refusal(s), s


async def test_stale_confirm_does_not_dispatch(monkeypatch):
    """Re-clicking the confirm button after the pending phase was consumed must emit an
    honest notice — never an EXECUTE MODE dispatch with an empty Task."""
    from server.services import phase_service

    async def _no_pending(conversation_id):
        return None

    dispatched = []

    async def _boom(*a, **kw):
        dispatched.append(1)

    monkeypatch.setattr(phase_service, "get_pending", _no_pending)
    monkeypatch.setattr(arslan, "_dispatch_spawn", _boom)
    events = []
    await arslan.confirm_and_execute("conv", 7, events.append)
    assert not dispatched                              # no ghost EXECUTE
    assert any(e["type"] == "message" and "提案" in e["content"] for e in events)


async def test_refusal_never_carried_as_direction(monkeypatch):
    """With a real pending direction but a refusal as the last output, the refusal must be
    dropped (prior_output=None) so the spawn does fresh work instead of role-playing it."""
    from server.orchestrator import dispatcher
    from server.services import phase_service

    async def _pending(conversation_id):
        return {"phase": "proposing", "spawn_id": 7, "direction": "调研OKX永续合约"}

    async def _last_output(spawn_id):
        return "I have zero remaining tool quota and cannot produce a deliverable."

    async def _clear(conversation_id, spawn_id=None):
        return None

    captured = {}

    async def _dispatch(conversation_id, spawn_id, direction, emit, **kw):
        captured.update(direction=direction, prior_output=kw.get("prior_output"))

    monkeypatch.setattr(phase_service, "get_pending", _pending)
    monkeypatch.setattr(phase_service, "clear", _clear)
    monkeypatch.setattr(dispatcher, "last_spawn_output", _last_output)
    monkeypatch.setattr(arslan, "_dispatch_spawn", _dispatch)
    await arslan.confirm_and_execute("conv", 7, lambda e: None)
    assert captured["direction"] == "调研OKX永续合约"   # the real task survives
    assert captured["prior_output"] is None            # the refusal does not


async def test_claimed_pptx_without_render_deck_forces_retry(monkeypatch):
    """'PPTX 已生成成功…你可以直接下载' without a render_deck call = a lie the guard must catch."""
    from tests.server.test_tool_loop import _ScriptedAdapter, _tools
    adapter = _ScriptedAdapter([
        "PPTX 已生成成功，共 5 页，原生可编辑。你可以直接下载该 .pptx 文件。",
        # honest correction, phrased so it trips no other guard (no 调用/生成-promise words)
        "抱歉，刚才的说法不准确——文件并不存在。需要的话请再确认一次。",
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await tool_loop.run(system="S", user_content="出个deck", history=[],
                              emit=lambda e: None, on_chunk=lambda c: None,
                              resolve_tools=_tools("render_deck"))
    # the false claim was intercepted; the honest correction is what survives
    assert "文件并不存在" in out["final"]
    assert len(adapter.calls) == 2                     # guard re-prompted exactly once


async def test_live_evasion_phrasings_now_caught():
    # the two phrasings that slipped past the first regex in the user's live test
    assert tool_loop._claims_deck("PPT 已正式生成并交付:")
    assert tool_loop._claims_deck("PPT 已生成并交付，共 10 页，原生可编辑，可直接下载。")
    # and legitimate mentions still pass free
    assert not tool_loop._claims_deck("如果需要 PPT,建议找 Deck Master")
    assert not tool_loop._claims_deck("我可以为你做一份PPT大纲")


async def test_claimed_deck_without_tool_forces_honesty(monkeypatch):
    """A spawn WITHOUT render_deck claiming delivery is a pure fabrication — the guard must
    force an honest correction (deliver as text + point to a deck-capable agent)."""
    from tests.server.test_tool_loop import _ScriptedAdapter, _tools
    adapter = _ScriptedAdapter([
        "PPT 已正式生成并交付，共 7 页。",
        # neutral honest correction — phrased to trip no other guard (no 制作/生成+PPT adjacency)
        "抱歉，我并没有真的产出文件——以上只是文字大纲。此类文件需要具备 Deck 能力的分身。",
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await tool_loop.run(system="S", user_content="出个PPT", history=[],
                              emit=lambda e: None, on_chunk=lambda c: None,
                              resolve_tools=_tools("web_search"))   # no render_deck wired
    assert "并没有真的产出文件" in out["final"]
    assert len(adapter.calls) == 2


def test_exhausted_round_salvages_evidence_into_fallback():
    """The 3-rounds-of-identical-searches incident: a spent round must leave its tool
    results in the final message so the next round builds on them instead of re-searching."""
    trace = [
        {"tool": "web_search", "args": {"query": "OKX perpetual pairs 2025"},
         "result": {"ok": True, "results": [{"title": "OKX lists 400+ perpetuals"}]}},
        {"tool": "web_extract", "args": {"url": "https://x.test/a"},
         "result": {"ok": False, "error": "http 403"}},          # failures excluded
    ]
    out = tool_loop._fallback_with_digest("帮我调研OKX永续合约", trace)
    assert "【阶段性发现】" in out
    assert "OKX lists 400+ perpetuals" in out
    assert "http 403" not in out                                  # failed steps don't pollute
    assert "回复" in out                                          # continue prompt still present
    # zero usable evidence → plain fallback, no empty digest header
    bare = tool_loop._fallback_with_digest("帮我调研OKX", [t for t in trace if not t["result"]["ok"]])
    assert "【阶段性发现】" not in bare


def test_digest_carrying_fallback_is_not_a_refusal():
    """The digest message ends with the same continue prompt, but it is substantive —
    the confirm path must CARRY it (dropping it restarts research from zero)."""
    msg = tool_loop._fallback_with_digest(
        "帮我调研OKX",
        [{"tool": "web_search", "args": {"query": "q"},
          "result": {"ok": True, "results": [{"title": "t"}]}}])
    assert not arslan._looks_like_refusal(msg)
    # while the bare (no-evidence) fallback is still treated as a refusal
    assert arslan._looks_like_refusal(tool_loop._fallback_message("帮我调研OKX"))
