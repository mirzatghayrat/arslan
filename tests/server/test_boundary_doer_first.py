"""组件2:doer-first 决策 — 点名才直派,推断则 Arslan 自己做 + 仅对 trusted 飘 chip。"""
import pytest

from server.orchestrator import arslan


class _NullSession:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


async def _aw(v):
    return v


@pytest.mark.asyncio
async def test_user_named_spawn_matches_name_and_at_mention(monkeypatch):
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw("Research Analyst"))
    assert await arslan._user_named_spawn("让 Research Analyst 深入查一下", 7) is True
    assert await arslan._user_named_spawn("@research analyst do it", 7) is True
    assert await arslan._user_named_spawn("查一下 github top10 ocr", 7) is False
    assert await arslan._user_named_spawn("", 7) is False


@pytest.mark.asyncio
async def test_user_named_spawn_false_when_no_name(monkeypatch):
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw(None))
    assert await arslan._user_named_spawn("anything", 7) is False


class _S:
    def __init__(self, sid, name):
        self.id, self.name = sid, name


@pytest.mark.asyncio
async def test_resolve_at_mentioned_spawn(monkeypatch):
    """Only an explicit @name resolves; a bare name does not; longest match wins."""
    monkeypatch.setattr(arslan.spawn_service, "load_all_spawns",
                        lambda: _aw([_S(3, "Deck Master"), _S(9, "Deck Master Pro"), _S(7, "Research Analyst")]))
    assert await arslan._resolve_at_mentioned_spawn("@Deck Master 你能干嘛") == 3
    assert await arslan._resolve_at_mentioned_spawn("@Deck Master Pro do it") == 9   # longest wins
    assert await arslan._resolve_at_mentioned_spawn("deck master 是谁") is None        # bare name, no @
    assert await arslan._resolve_at_mentioned_spawn("just a question") is None
    assert await arslan._resolve_at_mentioned_spawn("") is None


@pytest.mark.asyncio
async def test_inference_does_it_itself_and_chips_trusted(monkeypatch):
    answered, frames = [], []

    async def _answer(conv, msg, emit, **kw):
        answered.append(msg)
        emit({"type": "stream_end", "message_id": 1})
    monkeypatch.setattr(arslan, "_handle_answer", _answer)
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw("Research Analyst"))
    monkeypatch.setattr(arslan.db_session, "AsyncSessionLocal", lambda: _NullSession())
    monkeypatch.setattr(arslan.spawn_trust, "trust",
                        lambda session, sid: _aw({"band": "trusted", "tasks": 5, "accept_rate": 0.9}))

    dispatched = []
    monkeypatch.setattr(arslan, "_dispatch_spawn", lambda *a, **k: dispatched.append(a))
    parked = []
    monkeypatch.setattr(arslan.phase_service, "set_inviting",
                        lambda *a, **k: parked.append(k) or _aw(None))

    result = arslan.router.RouterResult(action="route", spawn_id=7, task_brief="深挖 X")
    await arslan._handle_route("main", result, frames.append, user_message="帮我深挖一下 X")

    assert answered == ["帮我深挖一下 X"]
    assert dispatched == []
    assert any(f.get("type") == "propose_invite" for f in frames)
    assert parked and parked[-1].get("announced") is True


@pytest.mark.asyncio
async def test_inference_green_no_chip(monkeypatch):
    frames = []

    async def _answer(conv, msg, emit, **kw):
        emit({"type": "stream_end", "message_id": 1})
    monkeypatch.setattr(arslan, "_handle_answer", _answer)
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw("Newbie"))
    monkeypatch.setattr(arslan.db_session, "AsyncSessionLocal", lambda: _NullSession())
    monkeypatch.setattr(arslan.spawn_trust, "trust",
                        lambda session, sid: _aw({"band": "green", "tasks": 0, "accept_rate": 0.0}))

    result = arslan.router.RouterResult(action="route", spawn_id=7, task_brief="做点 Y")
    await arslan._handle_route("main", result, frames.append, user_message="帮我做点 Y")
    assert not any(f.get("type") == "propose_invite" for f in frames)


@pytest.mark.asyncio
async def test_dual_track_grows_inferred_spawn(monkeypatch):
    # 组件5:推断分支里 Arslan 自己给了一版够长的产出 → 后台把产出喂给 router 推断的那个分身。
    long_answer = "半导体行业梳理:" + "。".join(f"要点{i}内容详实一段" for i in range(30))

    async def _answer(conv, msg, emit, **kw):
        emit({"type": "stream_end", "message_id": 1})
        return long_answer
    monkeypatch.setattr(arslan, "_handle_answer", _answer)
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw("Research Analyst"))
    monkeypatch.setattr(arslan.db_session, "AsyncSessionLocal", lambda: _NullSession())
    monkeypatch.setattr(arslan.spawn_trust, "trust",
                        lambda session, sid: _aw({"band": "green", "tasks": 0, "accept_rate": 0.0}))
    fired = []
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda sid, sig: fired.append((sid, sig)))

    result = arslan.router.RouterResult(action="route", spawn_id=7, task_brief="梳理半导体")
    await arslan._handle_route("main", result, lambda e: None, user_message="帮我梳理半导体行业现状")

    assert fired, "dual-track must fire for a substantive inferred-route answer"
    sid, sig = fired[-1]
    assert sid == 7
    assert "帮我梳理半导体行业现状" in sig
    assert "要点0内容详实一段" in sig


@pytest.mark.asyncio
async def test_dual_track_skips_short_answer(monkeypatch):
    async def _answer(conv, msg, emit, **kw):
        emit({"type": "stream_end", "message_id": 1})
        return "好的 👍"
    monkeypatch.setattr(arslan, "_handle_answer", _answer)
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw("Research Analyst"))
    monkeypatch.setattr(arslan.db_session, "AsyncSessionLocal", lambda: _NullSession())
    monkeypatch.setattr(arslan.spawn_trust, "trust",
                        lambda session, sid: _aw({"band": "green", "tasks": 0, "accept_rate": 0.0}))
    fired = []
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda sid, sig: fired.append((sid, sig)))

    result = arslan.router.RouterResult(action="route", spawn_id=7, task_brief="x")
    await arslan._handle_route("main", result, lambda e: None, user_message="随便聊聊")
    assert not fired


@pytest.mark.asyncio
async def test_scenario3_create_band_does_it_itself_then_suggests(monkeypatch):
    # 场景3:重复需求 + 无覆盖分身(create band)→ Arslan 先自己做,再飘轻 suggest_create chip。
    order = []

    async def _answer(conv, msg, emit, **kw):
        order.append("answer")
        emit({"type": "stream_end", "message_id": 1})
        return "我先给你做了一版草稿……"
    monkeypatch.setattr(arslan, "_handle_answer", _answer)
    monkeypatch.setattr(arslan.spawn_service, "load_all_spawns", lambda: _aw([]))
    monkeypatch.setattr(arslan.spawn_match_service, "score_spawns", lambda need, spawns: _aw([]))
    monkeypatch.setattr(arslan, "_fused_create_draft",
                        lambda slots, result, seeds: _aw({"name": "文案", "domain": "content.xhs"}))
    monkeypatch.setattr(arslan.spawn_service, "find_overlap", lambda draft, spawns: None)

    frames = []
    slots = {"domain": "content.xhs", "capability": "写小红书", "recurrence": True, "first_task": "写3条种草"}
    result = arslan.router.RouterResult(action="suggest_create", task_brief="写3条种草")
    await arslan._staffing_match_and_propose("main", "帮我写3条小红书种草", slots, result, frames.append)

    assert "answer" in order                                    # Arslan 先自己做了
    types = [f.get("type") for f in frames]
    assert "suggest_create" in types                            # 再飘建分身 chip
    assert types.index("stream_end") < types.index("suggest_create")


def test_scenario8_router_prompt_handles_multi_domain():
    # 场景8:多领域/含深度段的任务 → answer + Arslan 自己串,不整活派出去(router 判据显式化)。
    from server.orchestrator import router
    assert "MULTIPLE domains" in router._SYSTEM
    assert "stitches" in router._SYSTEM


@pytest.mark.asyncio
async def test_named_spawn_dispatches(monkeypatch):
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw("Deck Master"))
    monkeypatch.setattr(arslan.roster_service, "is_member", lambda *a, **k: _aw(True))
    answered = []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw(None))
    dispatched = []

    async def _disp(*a, **k):
        dispatched.append(a)
    monkeypatch.setattr(arslan, "_dispatch_spawn", _disp)

    result = arslan.router.RouterResult(action="route", spawn_id=7, task_brief="做张 deck")
    await arslan._handle_route("main", result, lambda e: None, user_message="让 Deck Master 做张 deck")
    assert dispatched and not answered
