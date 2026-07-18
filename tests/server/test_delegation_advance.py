"""PA-2 — deterministic delegation advance (确认循环 fix, 验收①②).

Live incident (thread-1783523936187): the router said route→spawn 6 FIVE consecutive
times; the user never literally named the spawn, so the doer-first gate self-answered
every turn, and the post-answer advancement chip was gated `band == "trusted"` — Deck
Master wasn't trusted, so the user had NO advancement channel → infinite confirm loop,
outline re-pasted 3×. These tests pin the two fixes:

  验收①: the chip is emitted for ANY band after a first-divert self-answer
         (propose_invite is itself the consent gate; band ≠ invitability), and after
         ONE user confirmation the turn MUST advance (invite card or dispatch) —
         never a second self-answer.
  验收②: short-confirm recognition is a deterministic bilingual lexicon — trim +
         lowercase + edge de-punctuation, exact or prefix match, zero LLM.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ChatMessage, ConversationEvent, RouterDecision, Spawn
from server.orchestrator import confirm_lexicon


@pytest.fixture(autouse=True)
def _gate_no_llm(monkeypatch):
    """BUG1 cell-6 domain gate hygiene: this file's maker harness is a REAL sqlite with
    EMPTY provider tables, so the gate's draft adapter would legacy-fall-back to a LIVE
    api.openai.com call from inside a unit test. Neutralize the gate's LLM leg (null =
    no contradiction = chip floats, the pre-gate behavior these tests pin). The gate
    itself is tested in test_task_arbitration.py."""
    from server.services import staffing_gather

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(staffing_gather, "extract_conflicting_domain", _none)

# ---------------------------------------------------------------------------
# Unit tier: the lexicon (验收②)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("msg", [
    "好", "好的", "好啊", "好嘞", "嗯", "嗯嗯", "行", "可以", "可",
    "就这样", "就这个", "直接出", "直接做", "直接来",
    "开始", "开始吧", "继续", "来吧", "做吧", "出吧", "快点",
    "怎么还不", "怎么还没出来", "几轮了", "还没好吗",
])
def test_lexicon_chinese_confirms(msg):
    assert confirm_lexicon.is_short_confirm(msg) is True


@pytest.mark.parametrize("msg", [
    "go", "yes", "y", "ok", "okay", "sure", "yep", "yeah",
    "do it", "go ahead", "proceed", "continue", "why not", "still waiting",
    "OK", "Yes", "GO AHEAD",  # case-insensitive
])
def test_lexicon_english_confirms(msg):
    assert confirm_lexicon.is_short_confirm(msg) is True


@pytest.mark.parametrize("msg", [
    "好的!", "好。", "  可以  ", "好👍", "👌ok", "ok!!", "yes.", "“好”",
    "开始吧~", "do it!", "继续,", "…继续", "行!!!",
])
def test_lexicon_tolerates_punctuation_and_emoji(msg):
    assert confirm_lexicon.is_short_confirm(msg) is True


def test_lexicon_prefix_matching():
    # multi-char entries also match as a prefix of a (short) message
    assert confirm_lexicon.is_short_confirm("开始吧,快") is True
    assert confirm_lexicon.is_short_confirm("可以的") is True
    assert confirm_lexicon.is_short_confirm("continue please") is True
    assert confirm_lexicon.is_short_confirm("怎么还不出") is True


@pytest.mark.parametrize("msg", [
    "", "   ", None,
    "帮我做一份半导体行业的PPT",
    # single-char entries are exact-only — negations/questions must not be swallowed
    "可是我不想要", "行不行", "好像不对",
    # ASCII prefix needs a word boundary — "go" must not swallow "google it"
    "google it", "yesterday was fine", "continued the report",
    # 验收② length cap: starts with 可以 but carries NEW SPEC — must NOT be swallowed
    # (the consecutive-route rule covers these, not the lexicon)
    "可以,但是把配色换成蓝色加金色点缀,再加一页市场规模数据",
    "ok but please switch the theme to dark glassmorphism first",
])
def test_lexicon_negatives(msg):
    assert confirm_lexicon.is_short_confirm(msg) is False


def test_lexicon_length_cap_boundary():
    # exactly at/below the cap with a lexicon prefix → confirm; past the cap → not
    assert len(confirm_lexicon.normalize("好的好的好的好的")) <= confirm_lexicon.MAX_NORMALIZED_LEN
    assert confirm_lexicon.is_short_confirm("好的好的好的好的") is True
    long = "可以" + "补" * confirm_lexicon.MAX_NORMALIZED_LEN
    assert confirm_lexicon.is_short_confirm(long) is False


# ---------------------------------------------------------------------------
# Unit tier: router.previous_decision (the consecutive-route lookup)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'advance.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        # NON-trusted by construction: a fresh spawn row, zero trust records (the
        # incident's Deck Master shape).
        s.add(Spawn(id=6, name="Deck Master", domain_category="content-creator",
                    capabilities=["deck"], system_prompt="You make decks."))
        await s.commit()

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_previous_decision_returns_second_latest(maker):
    from server.orchestrator import router

    async with db_session.AsyncSessionLocal() as s:
        s.add(RouterDecision(conversation_id="c1", user_message="m1", action="answer"))
        s.add(RouterDecision(conversation_id="c1", user_message="m2", action="route", spawn_id=6))
        s.add(RouterDecision(conversation_id="c2", user_message="other", action="route", spawn_id=9))
        s.add(RouterDecision(conversation_id="c1", user_message="m3", action="route", spawn_id=6))
        await s.commit()

    prev = await router.previous_decision("c1")  # latest is m3 (this turn) → previous is m2
    assert prev is not None
    assert prev.user_message == "m2"
    assert prev.action == "route" and prev.spawn_id == 6

    # a single row (this turn's own) has no previous
    assert await router.previous_decision("c2") is None
    # and an unknown conversation has none either
    assert await router.previous_decision("nope") is None


# ---------------------------------------------------------------------------
# Flow tier: the real _handle_route wiring (验收①)
# ---------------------------------------------------------------------------

# Long + honest (no promise_guard language) so the answer path streams untouched.
HONEST_ANSWER = ("这是我给你的一版半导体行业 PPT 大纲:第一章 行业概览与市场规模;第二章 供应链格局;"
                 "第三章 先进制程竞争;第四章 AI 芯片需求;第五章 政策与风险。每章配数据图表位与要点注释,"
                 "整体控制在十五页以内,风格采用暗色磨砂玻璃加金色点缀。")

LONG_TASK_MSG = "帮我做一份半导体行业的PPT,暗色磨砂玻璃加金色点缀风格"
LONG_FOLLOWUP_MSG = "把第二章换成设备材料环节,再补一页中国大陆产能数据,其他保持原来的大纲结构不变"


def _stub_answer_llm(monkeypatch):
    from server.orchestrator import dispatcher, tool_loop
    from tests.server.conftest import MockAdapter
    adapter = MockAdapter(chat_content=HONEST_ANSWER, stream_chunks=[HONEST_ANSWER])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: adapter)
    return adapter


def _stub_route(monkeypatch, *, action="route", spawn_id=6, task_brief="做半导体行业 PPT"):
    """A fake router that — like the real route() — PERSISTS its decision row before
    returning, so previous_decision sees the same table shape as production."""
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        result = router.RouterResult(action=action, spawn_id=spawn_id if action == "route" else None,
                                     task_brief=task_brief if action == "route" else None)
        await router._persist(conv, msg, action, result, {})
        return result

    monkeypatch.setattr(arslan.router, "route", _fake_route)


async def _events_of_kind(kind: str) -> list:
    async with db_session.AsyncSessionLocal() as s:
        evs = (await s.execute(select(ConversationEvent))).scalars().all()
    return [e for e in evs if e.kind == kind]


@pytest.mark.asyncio
async def test_turn1_divert_self_answers_and_chip_for_any_band(maker, monkeypatch):
    """验收① turn 1 — NON-trusted spawn, user does not name it, no prior decisions:
    the doer-first divert self-answers (allowed ONCE) AND the advancement chip
    (propose_invite) is emitted despite band != trusted."""
    from server.orchestrator import arslan
    from server.services import phase_service

    _stub_route(monkeypatch)
    _stub_answer_llm(monkeypatch)
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)

    dispatched = []

    async def _no_dispatch(*a, **k):
        dispatched.append(a)

    monkeypatch.setattr(arslan, "_dispatch_spawn", _no_dispatch)

    events = []
    await arslan.handle_user_message("main", LONG_TASK_MSG, events.append)

    # self-answer happened (streamed) and nothing was dispatched
    streamed = "".join(e.get("content", "") for e in events if e.get("type") == "stream_chunk")
    assert HONEST_ANSWER in streamed
    assert dispatched == []
    # THE chip — for a spawn with zero trust records
    chips = [e for e in events if e.get("type") == "propose_invite"]
    assert chips and chips[0]["spawn_id"] == 6
    # the task is parked for the chip's Accept
    invite = await phase_service.get_pending_invite("main")
    assert invite is not None and invite["spawn_id"] == 6
    assert invite["task_brief"] == "做半导体行业 PPT"
    # and this was a divert, not an advance
    assert await _events_of_kind("delegation_advance") == []


@pytest.mark.asyncio
async def test_turn2_short_confirm_advances_to_invite_no_second_answer(maker, monkeypatch):
    """验收① turn 2 — after a first divert, the user says 「好」: NO self-answer this
    time; the spawn is not in the roster → propose_invite with the parked brief."""
    from server.orchestrator import arslan
    from server.services import phase_service

    _stub_route(monkeypatch)
    _stub_answer_llm(monkeypatch)
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)
    await arslan.handle_user_message("main", LONG_TASK_MSG, lambda e: None)  # turn 1: divert
    # Turn 1's chip PARKED an invite; clear it so turn 2 exercises the ROUTE-advance
    # path (chip ignored/expired). The parked-invite typed-accept path is covered by
    # test_short_confirm_accepts_parked_invite.
    await phase_service.clear("main")

    answered = []

    async def _spy_answer(*a, **k):
        answered.append(a)

    monkeypatch.setattr(arslan, "_handle_answer", _spy_answer)

    events = []
    await arslan.handle_user_message("main", "好", events.append)  # turn 2: bare confirm

    assert answered == [], "a confirmed delegation must NEVER divert to a second self-answer"
    chips = [e for e in events if e.get("type") == "propose_invite"]
    assert chips and chips[0]["spawn_id"] == 6
    invite = await phase_service.get_pending_invite("main")
    assert invite is not None and invite["spawn_id"] == 6
    assert invite["task_brief"] == "做半导体行业 PPT"
    # audit: the advance was logged with its trigger
    advances = await _events_of_kind("delegation_advance")
    assert len(advances) == 1
    assert advances[0].ref["trigger"] == "short_confirm"
    assert advances[0].ref["spawn_id"] == 6


@pytest.mark.asyncio
async def test_turn2_short_confirm_roster_member_dispatches(maker, monkeypatch):
    """Roster-member variant: the confirmed spawn is already in the roster → the turn
    dispatches directly (spawn memory gets the exchange), no invite card, no answer."""
    from server.orchestrator import arslan
    from server.services import roster_service

    _stub_route(monkeypatch)
    _stub_answer_llm(monkeypatch)
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)
    await roster_service.join("main", 6, via="invited")
    await arslan.handle_user_message("main", LONG_TASK_MSG, lambda e: None)
    # Turn 1's chip parked an invite; clear it so turn 2 exercises the ROUTE-advance
    # dispatch path (typed-accept of a parked invite is covered separately).
    from server.services import phase_service
    await phase_service.clear("main")  # turn 1...

    answered = []

    async def _spy_answer(*a, **k):
        answered.append(a)

    monkeypatch.setattr(arslan, "_handle_answer", _spy_answer)

    events = []
    await arslan.handle_user_message("main", "好", events.append)

    assert answered == []
    assert not any(e.get("type") == "propose_invite" for e in events)
    # dispatch really happened — the spawn's own memory has the exchange (smoke-test shape)
    async with db_session.AsyncSessionLocal() as s:
        cms = (await s.execute(select(ChatMessage))).scalars().all()
    assert {c.role for c in cms} >= {"user", "assistant"}
    advances = await _events_of_kind("delegation_advance")
    assert len(advances) == 1 and advances[0].ref["trigger"] == "short_confirm"


@pytest.mark.asyncio
async def test_consecutive_route_advances_without_short_confirm(maker, monkeypatch):
    """Trigger (a) alone: the previous decision was route→the SAME spawn, and the new
    message is LONG (new spec, not a bare confirm) — must still advance, because the
    router re-affirming the same specialist after one divert IS the confirm loop."""
    from server.orchestrator import arslan

    _stub_route(monkeypatch)
    _stub_answer_llm(monkeypatch)
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)
    await arslan.handle_user_message("main", LONG_TASK_MSG, lambda e: None)  # turn 1: divert
    # Turn 1's chip PARKED an invite; clear it so turn 2 exercises the ROUTE-advance
    # path (chip ignored/expired). The parked-invite typed-accept path is covered by
    # test_short_confirm_accepts_parked_invite.
    from server.services import phase_service
    await phase_service.clear("main")

    answered = []

    async def _spy_answer(*a, **k):
        answered.append(a)

    monkeypatch.setattr(arslan, "_handle_answer", _spy_answer)

    assert confirm_lexicon.is_short_confirm(LONG_FOLLOWUP_MSG) is False  # trigger isolation
    events = []
    await arslan.handle_user_message("main", LONG_FOLLOWUP_MSG, events.append)

    assert answered == []
    assert any(e.get("type") == "propose_invite" for e in events)
    advances = await _events_of_kind("delegation_advance")
    assert len(advances) == 1
    assert advances[0].ref["trigger"] == "consecutive_route"


@pytest.mark.asyncio
async def test_short_confirm_advances_without_consecutive_route(maker, monkeypatch):
    """Trigger (b) alone: the previous decision was `answer` (NOT route-same-spawn) and
    the user sends a bare confirm — must advance on the lexicon trigger."""
    from server.orchestrator import arslan

    _stub_answer_llm(monkeypatch)
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)
    _stub_route(monkeypatch, action="answer")
    await arslan.handle_user_message("main", "先随便聊聊半导体行业", lambda e: None)  # turn 1: answer

    _stub_route(monkeypatch)  # turn 2: router now wants spawn 6

    answered = []

    async def _spy_answer(*a, **k):
        answered.append(a)

    monkeypatch.setattr(arslan, "_handle_answer", _spy_answer)

    events = []
    await arslan.handle_user_message("main", "可以", events.append)

    assert answered == []
    assert any(e.get("type") == "propose_invite" for e in events)
    advances = await _events_of_kind("delegation_advance")
    assert len(advances) == 1 and advances[0].ref["trigger"] == "short_confirm"


@pytest.mark.asyncio
async def test_neither_trigger_preserves_doer_first_divert(maker, monkeypatch):
    """Neither trigger: previous decision was `answer`, message is a long fresh task →
    the doer-first divert stands (self-answer + chip), exactly as before PA-2."""
    from server.orchestrator import arslan

    _stub_answer_llm(monkeypatch)
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)
    _stub_route(monkeypatch, action="answer")
    await arslan.handle_user_message("main", "先随便聊聊半导体行业", lambda e: None)

    _stub_route(monkeypatch)

    dispatched = []

    async def _no_dispatch(*a, **k):
        dispatched.append(a)

    monkeypatch.setattr(arslan, "_dispatch_spawn", _no_dispatch)

    events = []
    await arslan.handle_user_message("main", LONG_TASK_MSG, events.append)

    streamed = "".join(e.get("content", "") for e in events if e.get("type") == "stream_chunk")
    assert HONEST_ANSWER in streamed          # self-answer (divert) happened
    assert dispatched == []                   # no dispatch
    assert any(e.get("type") == "propose_invite" for e in events)  # chip still floats (验收①)
    assert await _events_of_kind("delegation_advance") == []


# ---------------------------------------------------------------------------
# PA-4: repeated_confirmation completion-degree signal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_confirm_advance_logs_repeated_confirmation(maker, monkeypatch):
    """PA-4: a short-confirm that fires the PA-2 advance IS a repeated confirmation —
    the advance site also logs a countable repeated_confirmation event (count=1)."""
    from server.orchestrator import arslan

    _stub_route(monkeypatch)
    _stub_answer_llm(monkeypatch)
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)
    await arslan.handle_user_message("main", LONG_TASK_MSG, lambda e: None)  # turn 1: divert
    # Turn 1's chip PARKED an invite; clear it so turn 2 exercises the ROUTE-advance
    # path (chip ignored/expired). The parked-invite typed-accept path is covered by
    # test_short_confirm_accepts_parked_invite.
    from server.services import phase_service
    await phase_service.clear("main")
    await arslan.handle_user_message("main", "好", lambda e: None)           # turn 2: confirm

    rc = await _events_of_kind("repeated_confirmation")
    assert len(rc) == 1
    assert rc[0].ref["count"] == 1
    assert rc[0].ref["spawn_id"] == 6
    assert "×1" in rc[0].summary
    # the long turn-1 task message never logs one
    assert all("半导体" not in (e.summary or "") for e in rc)


@pytest.mark.asyncio
async def test_answer_path_short_confirm_logs_repeated_confirmation_count(maker, monkeypatch):
    """PA-4: a short-confirm the router classifies as plain `answer` (no advance
    machinery runs) still logs repeated_confirmation, with a running per-conversation
    count — the cheap completion-degree signal for answer-path turns."""
    from server.orchestrator import arslan

    _stub_answer_llm(monkeypatch)
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)
    _stub_route(monkeypatch, action="answer")

    await arslan.handle_user_message("main", "好", lambda e: None)       # count 1
    await arslan.handle_user_message("main", "继续", lambda e: None)     # count 2
    await arslan.handle_user_message("main", "先随便聊聊半导体行业", lambda e: None)  # NOT a confirm

    rc = await _events_of_kind("repeated_confirmation")
    assert [e.ref["count"] for e in rc] == [1, 2]
    # counts are per-conversation: another conversation starts at 1
    await arslan.handle_user_message("other", "好", lambda e: None)
    async with db_session.AsyncSessionLocal() as s:
        evs = (await s.execute(select(ConversationEvent))).scalars().all()
    other = [e for e in evs if e.kind == "repeated_confirmation" and e.conversation_id == "other"]
    assert len(other) == 1 and other[0].ref["count"] == 1


# ---------------------------------------------------------------------------
# Typing consent accepts a parked invite (PA-6 real-machine gap):
# a pending inline invite + a short confirm must dispatch the parked brief —
# exactly like clicking Accept. The router must never see the message.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_confirm_accepts_parked_invite(maker, monkeypatch):
    import server.orchestrator.arslan as arslan_mod
    from server.services import phase_service

    await phase_service.set_inviting(
        "conv-inv", 6, task_brief="做一份新能源简报", user_message="给我出一份简报PPT",
        needs_proposal=False, announced=True)

    calls: list[dict] = []

    async def _spy_dispatch(conversation_id, spawn_id, task_brief, needs_proposal, emit, **kw):
        calls.append({"conv": conversation_id, "spawn_id": spawn_id,
                      "task_brief": task_brief, "needs_proposal": needs_proposal, **kw})

    monkeypatch.setattr(arslan_mod, "dispatch_routed", _spy_dispatch)

    async def _router_must_not_run(conv, msg):  # noqa: ANN001
        raise AssertionError("router.route must not be called on a typed invite-accept")

    monkeypatch.setattr(arslan_mod.router, "route", _router_must_not_run)

    events: list[dict] = []
    await arslan_mod.handle_user_message("conv-inv", "好", events.append)

    assert len(calls) == 1
    assert calls[0]["spawn_id"] == 6
    assert calls[0]["task_brief"] == "做一份新能源简报"
    assert calls[0]["announce"] is False          # Arslan spoke the brief before the card
    assert await phase_service.get_pending_invite("conv-inv") is None   # phase cleared

    rows = await _events_of_kind("delegation_advance")
    assert any(r.conversation_id == "conv-inv" for r in rows)


@pytest.mark.asyncio
async def test_non_confirm_clears_stale_invite(maker, monkeypatch):
    """Bug B (stale parked-invite mis-fire): a parked invite is honored ONLY as the
    IMMEDIATE next user action. If the user ignores the chip and sends anything that is
    NOT a bare confirm, the invite is cleared — so a LATER bare 「好」 (e.g. agreeing with
    something else Arslan said N turns later) can NOT deterministically mis-dispatch the
    stale task. The frontend already implicitly dismisses the chip UI on send (via
    dismissAllPending) but sends no dismiss_invite; this makes the backend consistent.

    (Was `test_non_confirm_leaves_invite_parked`, which asserted the invite STAYED parked
    across an intervening turn — that encoded the Bug B trap and is deliberately inverted.)"""
    import server.orchestrator.arslan as arslan_mod
    from server.orchestrator.router import RouterResult
    from server.services import phase_service

    await phase_service.set_inviting(
        "conv-inv2", 6, task_brief="brief", user_message="orig",
        needs_proposal=False, announced=True)

    dispatched: list[int] = []

    async def _spy_dispatch(*a, **kw):  # noqa: ANN001
        dispatched.append(1)

    monkeypatch.setattr(arslan_mod, "dispatch_routed", _spy_dispatch)

    async def _route_answer(conv, msg):  # noqa: ANN001
        return RouterResult(action="answer", reason="test")

    monkeypatch.setattr(arslan_mod.router, "route", _route_answer)

    from tests.server.conftest import MockAdapter
    adapter = MockAdapter(chat_content="收到,你想聚焦哪块?", stream_chunks=["收到,你想聚焦哪块?"])
    monkeypatch.setattr(arslan_mod, "_get_adapter", lambda: adapter, raising=False)
    from server.orchestrator import tool_loop as tl
    monkeypatch.setattr(tl, "_get_adapter", lambda: adapter)

    # Intervening NON-confirm turn: not an accept, and it clears the stale invite.
    events: list[dict] = []
    await arslan_mod.handle_user_message("conv-inv2", "换个主题,做人工智能方向的", events.append)
    assert dispatched == []                                             # not treated as accept
    assert await phase_service.get_pending_invite("conv-inv2") is None  # stale invite cleared (Bug B)

    # A LATER bare 「好」 must fall through to normal routing (answer), NOT dispatch the
    # now-cleared stale task.
    await arslan_mod.handle_user_message("conv-inv2", "好", lambda e: None)
    assert dispatched == []                                             # no delayed mis-fire
