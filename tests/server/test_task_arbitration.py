"""Delegation route-to-member arbitration — the §1.5 truth table, one test per cell.

This is the single most bug-prone surface (S0-2, PA, and now this all live in
`_handle_route`). Every cell of the arbitration truth table gets exactly one test, named
for its cell. Two of these reproduce the real-machine bugs FIRST (they are RED on the
pre-fix code):

  - cell 4 (Bug 2): an INFERRED route to a spawn already in the roster used to fall into
    the doer-first branch (Arslan answered + invited) instead of dispatching directly.
  - cell 6 accept (Bug 1): accepting a recruiting invite re-dispatched the task Arslan had
    ALREADY answered doer-first (duplicate answer + double token).

The arbitration is tested deterministically with monkeypatch stubs (no real LLM):
`_handle_answer`, `dispatch_routed`, `roster_service.is_member`, `score_spawns` (over which
the REAL `classify_band` runs), `roster_service.join`, and an `emit` frame capture.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn
from server.orchestrator import arslan
from server.services import phase_service


# --------------------------------------------------------------------------- helpers


async def _aw(v):
    return v


def _route_result(spawn_id=7, task_brief="做点 X", needs_proposal=False):
    return arslan.router.RouterResult(
        action="route", spawn_id=spawn_id, task_brief=task_brief, needs_proposal=needs_proposal
    )


def _stub_member_scoring(monkeypatch, ranked):
    """Feed the inferred-route member scoring a controlled ranked list so the REAL
    `classify_band` (real STRONG/MARGIN/LOW thresholds) decides the band, while the
    DB-backed loaders return trivially (score_spawns ignores its args here)."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        arslan.spawn_service, "load_one_spawn",
        lambda sid: _aw(SimpleNamespace(
            domain_category="marketing", domain_subcategory="deck", capabilities=["deck"])),
    )
    monkeypatch.setattr(arslan.spawn_service, "load_all_spawns", lambda: _aw([]))
    monkeypatch.setattr(arslan.roster_service, "list_roster", lambda conv: _aw([]))
    monkeypatch.setattr(arslan.spawn_match_service, "score_spawns",
                        lambda need, spawns: _aw(ranked))


def _stub_arbitration_env(monkeypatch, *, is_member, ranked=None):
    """Common deterministic environment for an INFERRED-route arbitration test."""
    monkeypatch.setattr(arslan.roster_service, "is_member", lambda *a, **k: _aw(is_member))
    monkeypatch.setattr(arslan.router, "previous_decision", lambda conv: _aw(None))
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw("Deck Master"))
    if ranked is not None:
        _stub_member_scoring(monkeypatch, ranked)


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    """Real sqlite for the accept-path cells (typed-「好」 spine goes through
    `handle_user_message` + `phase_service` + `memory`, which need a live DB)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'arb.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(Spawn(
            id=7, name="Deck Master", domain_category="marketing",
            domain_subcategory="deck", capabilities=["deck"],
            persona_role="builds decks", system_prompt="You build decks."))
        await s.commit()

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


# --------------------------------------------------------------------------- cell 4 (Bug 2)


@pytest.mark.asyncio
async def test_cell4_inferred_member_direct_dispatch(monkeypatch):
    """Cell 4 (Bug 2 reproduce→fix): an INFERRED route whose target IS a roster member
    scoring a clean single fit (invite_one, top == routed) dispatches DIRECTLY — Arslan
    does NOT self-answer and NO invite card is popped. (Pre-fix: doer-first answered +
    invited, shadowing the member dispatch — RED.)"""
    _stub_arbitration_env(monkeypatch, is_member=True, ranked=[
        {"spawn_id": 7, "name": "Deck Master", "score": 0.9, "why": "domain 1.0, coverage 0.9"},
    ])
    answered, dispatched, parked, frames = [], [], [], []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw(None))

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)
    monkeypatch.setattr(arslan.phase_service, "set_inviting",
                        lambda *a, **k: parked.append(k) or _aw(None))

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="帮我搞个演示文稿")

    assert len(dispatched) == 1, "inferred member (invite_one) must dispatch directly"
    assert dispatched[0][0][1] == 7
    assert answered == [], "Arslan must NOT self-answer when a capable member takes it"
    assert not any(f.get("type") == "propose_invite" for f in frames), "no invite card"
    assert parked == [], "nothing parked — the member just takes the task"


# --------------------------------------------------------------------------- cell 6 (Bug 1)


@pytest.mark.asyncio
async def test_cell6_inferred_nonmember_answers_and_recruit_invite(monkeypatch):
    """Cell 6 (route side): an INFERRED route to a NON-member → Arslan answers doer-first
    AND pops a RECRUITING invite whose park carries answered=True."""
    _stub_arbitration_env(monkeypatch, is_member=False)
    # The BUG1 domain gate has its own tests below; force it OFF here so this test
    # (no maker fixture → production sessionmaker) never reaches the real DB/LLM
    # through the gate's load_all_spawns/draft-adapter path.
    monkeypatch.setattr(arslan, "_recruit_domain_conflict", lambda *a, **k: _aw(False))
    answered, dispatched, parked, frames = [], [], [], []

    async def _answer(conv, msg, emit, **kw):
        answered.append(msg)
        emit({"type": "stream_end", "message_id": 1})
        return "详实产出" * 60  # ≥ _DUAL_TRACK_MIN_CHARS
    monkeypatch.setattr(arslan, "_handle_answer", _answer)

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)
    monkeypatch.setattr(arslan.phase_service, "set_inviting",
                        lambda *a, **k: parked.append(k) or _aw(None))
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)

    await arslan._handle_route("main", _route_result(7, task_brief="做半导体 PPT"),
                               frames.append, user_message="帮我做半导体行业 PPT")

    assert answered == ["帮我做半导体行业 PPT"], "Arslan answers doer-first"
    assert dispatched == [], "recruit invite must NOT dispatch (Arslan already answered)"
    assert any(f.get("type") == "propose_invite" for f in frames), "recruit invite card"
    assert parked and parked[-1].get("answered") is True, "park marks the invite answered"
    assert parked[-1].get("task_brief") == "做半导体 PPT"


@pytest.mark.asyncio
async def test_cell6_accept_joins_only_no_redispatch(maker, monkeypatch):
    """Cell 6 accept (Bug 1 reproduce→fix): accepting a RECRUITING invite (answered=True)
    ONLY enrolls the spawn + posts a note — it must NOT re-dispatch the already-answered
    task. (Pre-fix: the typed-「好」 spine re-dispatched the parked brief — RED.)"""
    joined, dispatched, frames, recaps = [], [], [], []

    async def _join(conv, sid, *, via):
        joined.append((conv, sid, via))
        return True
    monkeypatch.setattr(arslan.roster_service, "join", _join)

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)

    from server.services import recap_service

    async def _recap(conv, kind, payload, summary):
        recaps.append((kind, summary))
    monkeypatch.setattr(recap_service, "log_event", _recap)

    await phase_service.set_inviting("main", 7, task_brief="做半导体 PPT",
                                     user_message="帮我做半导体行业 PPT", answered=True)

    await arslan.handle_user_message("main", "好", frames.append)

    assert joined and joined[-1][1] == 7, "recruit accept must ENROLL the spawn"
    assert dispatched == [], "recruit accept must NOT re-dispatch the answered task"
    assert any(f.get("type") == "roster_event" and f.get("action") == "recruited"
               for f in frames), "a recruit note must be posted"
    assert await phase_service.get_pending_invite("main") is None, "pending invite cleared"
    # Honest copy (BUG1): the roster is session-ephemeral and no routing preference
    # is persisted, so the recap must not claim "下次这类任务直接接手".
    invite_recaps = [s for k, s in recaps if k == "invite"]
    assert invite_recaps, "recruit accept must log an invite recap"
    assert all("下次" not in s for s in invite_recaps), "recap claims an unbacked 下次 promise"
    assert any("本次会话" in s for s in invite_recaps), "recap should state the session scope"


# --------------------------------------------------------------------------- cell 6 gate (BUG1)


def _spawn_ns(sid, name, cat, sub):
    from types import SimpleNamespace

    return SimpleNamespace(id=sid, name=name, domain_category=cat,
                           domain_subcategory=sub, capabilities=[])


def _cell6_env(monkeypatch):
    """Deterministic cell-6 flow env + capture lists (answered/parked/frames/dual).

    Registry: pick 7 = engineering.software-development, other = marketing.* — the
    gate's DB leg is stubbed here; its LLM leg is stubbed per-test."""
    _stub_arbitration_env(monkeypatch, is_member=False)
    answered, parked, frames, dual = [], [], [], []

    async def _answer(conv, msg, emit, **kw):
        answered.append(msg)
        emit({"type": "stream_end", "message_id": 1})
        return "详实产出" * 60  # ≥ _DUAL_TRACK_MIN_CHARS
    monkeypatch.setattr(arslan, "_handle_answer", _answer)
    monkeypatch.setattr(arslan.phase_service, "set_inviting",
                        lambda *a, **k: parked.append(k) or _aw(None))
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: dual.append(a))
    monkeypatch.setattr(
        arslan.spawn_service, "load_all_spawns",
        lambda: _aw([_spawn_ns(7, "Coding Assistant", "engineering", "software-development"),
                     _spawn_ns(3, "Copywriter", "marketing", "content-copywriting")]))
    return answered, parked, frames, dual


@pytest.mark.asyncio
async def test_cell6_domain_contradiction_suppresses_chip_and_dual_track(monkeypatch):
    """BUG1: an affirmative, registry-anchored domain contradiction suppresses the
    RECRUITING chip AND the dual-track feed (feeding the deliverable would grow the
    WRONG spawn's well). The doer-first answer stands alone."""
    answered, parked, frames, dual = _cell6_env(monkeypatch)
    seen = {}

    async def _conflict(task_text, pick_domain, others):
        seen.update(text=task_text, pick=pick_domain, others=others)
        return "marketing.content-copywriting"
    monkeypatch.setattr(arslan.staffing_gather, "extract_conflicting_domain", _conflict)

    await arslan._handle_route("main", _route_result(7, task_brief="报告图表改 Mermaid"),
                               frames.append, user_message="把报告里的 CSS 图换成 Mermaid")

    assert answered, "doer-first answer unchanged"
    assert not any(f.get("type") == "propose_invite" for f in frames), "chip suppressed"
    assert parked == [], "no park on suppression"
    assert dual == [], "dual-track must not grow the wrong-domain spawn"
    assert seen["pick"] == "engineering.software-development"
    assert seen["others"] == ["marketing.content-copywriting"]


@pytest.mark.asyncio
async def test_cell6_no_contradiction_keeps_chip_and_dual_track(monkeypatch):
    """PA-2 preserved: a null (no clear contradiction) floats the chip exactly as
    before, park answered=True, dual-track fires."""
    answered, parked, frames, dual = _cell6_env(monkeypatch)

    async def _conflict(*a, **k):
        return None
    monkeypatch.setattr(arslan.staffing_gather, "extract_conflicting_domain", _conflict)

    await arslan._handle_route("main", _route_result(7, task_brief="修个 CI 脚本"),
                               frames.append, user_message="帮我修 CI 脚本")

    assert any(f.get("type") == "propose_invite" for f in frames), "chip floats on null"
    assert parked and parked[-1].get("answered") is True
    assert dual, "dual-track fires when the chip is not suppressed"


@pytest.mark.asyncio
async def test_cell6_off_list_answer_and_none_task_brief_float(monkeypatch):
    """Belt: an off-list answer (LLM went off the registry vocabulary) is treated as
    unknown → chip floats; a None task_brief must not leak a literal 'None' into the
    extraction text."""
    answered, parked, frames, dual = _cell6_env(monkeypatch)
    seen = {}

    async def _conflict(task_text, pick_domain, others):
        seen["text"] = task_text
        return "weird-freeform.x"  # category not in the registry → must NOT suppress
    monkeypatch.setattr(arslan.staffing_gather, "extract_conflicting_domain", _conflict)

    await arslan._handle_route("main", _route_result(7, task_brief=None),
                               frames.append, user_message="帮我整理一下")

    assert any(f.get("type") == "propose_invite" for f in frames), "off-list → chip floats"
    assert "None" not in seen["text"]


@pytest.mark.asyncio
async def test_cell6_gate_failure_floats_chip_no_crash(monkeypatch):
    """Fail-open: ANY infrastructure failure inside the gate (DB here) floats the chip
    and never crashes the turn — the answer already streamed (PA-2: chip-death is the
    documented worse failure)."""
    answered, parked, frames, dual = _cell6_env(monkeypatch)

    async def _boom():
        raise RuntimeError("db exploded")
    monkeypatch.setattr(arslan.spawn_service, "load_all_spawns", _boom)

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="帮我做点事")

    assert any(f.get("type") == "propose_invite" for f in frames), "fail-open: chip floats"
    assert parked and parked[-1].get("answered") is True


@pytest.mark.asyncio
async def test_cell6_gate_timeout_floats_chip(monkeypatch):
    """A dead-but-reachable draft adapter must not hang the turn: the gate is bounded
    by _RECRUIT_GATE_TIMEOUT_S and a timeout floats the chip."""
    answered, parked, frames, dual = _cell6_env(monkeypatch)
    monkeypatch.setattr(arslan, "_RECRUIT_GATE_TIMEOUT_S", 0.05)
    import asyncio as _asyncio

    async def _slow(*a, **k):
        await _asyncio.sleep(0.5)
        return "marketing.content-copywriting"
    monkeypatch.setattr(arslan.staffing_gather, "extract_conflicting_domain", _slow)

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="帮我做点事")

    assert any(f.get("type") == "propose_invite" for f in frames), "timeout → chip floats"


# --------------------------------------------------------------------------- cell 3


@pytest.mark.asyncio
async def test_cell3_escape_hatch_arslan_answers_despite_member(monkeypatch):
    """Cell 3: the user explicitly addressed Arslan ("@Arslan"/"你直接答") — Arslan answers
    even though a strong capable member exists. No dispatch, no card. (Mirror of the @spawn
    override, and it wins over the member routing.)"""
    _stub_arbitration_env(monkeypatch, is_member=True, ranked=[
        {"spawn_id": 7, "name": "Deck Master", "score": 0.95, "why": "strong"},
    ])
    answered, dispatched, parked, frames = [], [], [], []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw(None))

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)
    monkeypatch.setattr(arslan.phase_service, "set_inviting",
                        lambda *a, **k: parked.append(k) or _aw(None))

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="@Arslan 你直接答:帮我做张 deck")

    assert answered == [1], "escape hatch → Arslan answers"
    assert dispatched == [], "no dispatch"
    assert parked == [], "no invite parked"
    assert not any(f.get("type") in ("propose_invite", "clarify_options") for f in frames)


# --------------------------------------------------------------------------- cell 5


@pytest.mark.asyncio
async def test_cell5_ambiguous_members_picker_not_silent(monkeypatch):
    """Cell 5: ≥2 roster members plausibly fit (picker band) → Arslan pops an
    ask_user_choice (clarify_options) card and parks a choice — it does NOT silently
    dispatch the router's guess, and does NOT self-answer."""
    _stub_arbitration_env(monkeypatch, is_member=True, ranked=[
        {"spawn_id": 7, "name": "Deck Master", "score": 0.86, "why": "a"},
        {"spawn_id": 8, "name": "Slide Smith", "score": 0.80, "why": "b"},
    ])
    answered, dispatched, chosen, frames = [], [], [], []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw(None))

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)
    monkeypatch.setattr(arslan.phase_service, "set_choosing",
                        lambda *a, **k: chosen.append(k) or _aw(None))

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="帮我搞个演示")

    clar = [f for f in frames if f.get("type") == "clarify_options"]
    assert clar, "ambiguous members must pop an ask_user_choice card"
    labels = [o["label"] for o in clar[0]["options"]]
    assert "Deck Master" in labels and "Slide Smith" in labels
    assert dispatched == [], "must not silently dispatch the router's guess"
    assert answered == [], "must not self-answer either"
    assert chosen and {c["spawn_id"] for c in chosen[-1]["candidates"]} == {7, 8}


@pytest.mark.asyncio
async def test_cell5_pick_dispatches_to_chosen_member(maker, monkeypatch):
    """Cell 5 accept: the user's pick (the chosen member's name, sent back by the picker
    card) dispatches the parked task to THAT member with its original brief."""
    dispatched, frames = [], []

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)

    await phase_service.set_choosing(
        "main",
        candidates=[{"spawn_id": 7, "name": "Deck Master"},
                    {"spawn_id": 8, "name": "Slide Smith"}],
        task_brief="做半导体 PPT", user_message="帮我做半导体行业 PPT")

    await arslan.handle_user_message("main", "Deck Master", frames.append)

    assert len(dispatched) == 1, "the pick dispatches to the chosen member"
    assert dispatched[0][0][1] == 7, "picked member id"
    assert dispatched[0][0][2] == "做半导体 PPT", "with the original parked brief"
    assert await phase_service.get_pending_choice("main") is None, "choice cleared"


# --------------------------------------------------------------------------- cell 2 (S0-2)


@pytest.mark.asyncio
async def test_cell2_named_nonmember_parks_unanswered_and_accept_dispatches(maker, monkeypatch):
    """Cell 2 (S0-2 guard): @naming a NON-member parks the task UNANSWERED (Arslan does not
    answer) + pops the invite; accepting it DISPATCHES the parked task (not join-only)."""
    monkeypatch.setattr(arslan, "_user_named_spawn", lambda *a, **k: _aw(True))
    monkeypatch.setattr(arslan.roster_service, "is_member", lambda *a, **k: _aw(False))
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw("Deck Master"))
    monkeypatch.setattr(arslan, "_route_announcement", lambda *a, **k: _aw("brief @Deck Master"))
    monkeypatch.setattr(arslan, "_invite_capability_summary", lambda sid: _aw("builds decks"))
    answered = []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw(None))
    dispatched = []

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)

    frames = []
    await arslan._handle_route("main", _route_result(7, task_brief="做张 deck"),
                               frames.append, user_message="让 Deck Master 做张 deck")

    assert answered == [], "cell 2 must NOT self-answer (task parked unanswered)"
    assert any(f.get("type") == "propose_invite" for f in frames), "invite card"
    parked = await phase_service.get_pending_invite("main")
    assert parked is not None and not parked.get("answered"), "parked UNANSWERED"
    assert parked["task_brief"] == "做张 deck"

    # Accept via typed 「好」 → the unanswered task DISPATCHES (S0-2 not regressed).
    await arslan.handle_user_message("main", "好", frames.append)
    assert len(dispatched) == 1 and dispatched[0][0][1] == 7, "accept dispatches the parked task"


# --------------------------------------------------------------------------- cell 7


@pytest.mark.asyncio
async def test_cell7_no_capable_member_staffing(monkeypatch):
    """Cell 7: the router routed to a roster member that scores create-band (not actually a
    fit) → Arslan answers doer-first. No dispatch, no recruit invite, no picker. (From a
    route action there are no gathered staffing slots, so the suggest_create staffing spine
    — the `suggest_create` router action, untouched — is not synthesized here.)"""
    _stub_arbitration_env(monkeypatch, is_member=True, ranked=[
        {"spawn_id": 7, "name": "Deck Master", "score": 0.30, "why": "weak"},
    ])
    answered, dispatched, parked, frames = [], [], [], []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw("短答"))

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)
    monkeypatch.setattr(arslan.phase_service, "set_inviting",
                        lambda *a, **k: parked.append(k) or _aw(None))
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="帮我搞个演示")

    assert answered == [1], "cell 7 → Arslan answers doer-first"
    assert dispatched == [], "no dispatch (member is not a real fit)"
    assert parked == [], "no recruit invite (no capable non-member to recruit)"
    assert not any(f.get("type") == "propose_invite" for f in frames)
    assert not any(f.get("type") == "clarify_options" for f in frames)


# --------------------------------------------------------------------------- S0-2 park guard


@pytest.mark.asyncio
async def test_s02_staffing_park_still_dispatches_on_accept(maker, monkeypatch):
    """S0-2 regression guard: a park with NO answered flag (an UNanswered task, as staffing
    and cell 2 produce) still DISPATCHES on typed-「好」 accept — the answered-recruit path
    must not swallow the ordinary parked-invite dispatch."""
    dispatched, frames = [], []

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)
    joined = []

    async def _join(conv, sid, *, via):
        joined.append(sid)
        return True
    monkeypatch.setattr(arslan.roster_service, "join", _join)

    await phase_service.set_inviting("main", 7, task_brief="draft a post",
                                     user_message="help me on linkedin")  # answered defaults False

    await arslan.handle_user_message("main", "好", frames.append)

    assert len(dispatched) == 1 and dispatched[0][0][1] == 7, "ordinary park dispatches"
    assert joined == [], "it does not join-only"
    assert not any(f.get("type") == "roster_event" and f.get("action") == "recruited"
                   for f in frames)


# --------------------------------------------------------------------------- escape-hatch unit


def test_user_addressed_arslan_phrase_set():
    """The conservative escape-hatch phrase set (Fix 1b): EVERY phrase carries an explicit
    Arslan address (@arslan/主脑) OR a 你-anchored 'you answer'. Pronoun-less phrases are
    DELIBERATELY excluded so ordinary task text can't trip the escape hatch."""
    assert arslan._user_addressed_arslan("@Arslan 你来答") is True
    assert arslan._user_addressed_arslan("@arslan handle it") is True
    assert arslan._user_addressed_arslan("你直接答就行") is True
    assert arslan._user_addressed_arslan("主脑你来答这个") is True     # matches 你来答
    assert arslan._user_addressed_arslan("让主脑答这个问题") is True   # anchored 主脑 variant
    assert arslan._user_addressed_arslan("arslan 你答") is True        # anchored host variant
    # Fix 1b: pronoun-less phrases NO LONGER escape — they false-positive on task text.
    assert arslan._user_addressed_arslan("直接回答我") is False        # was True (over-match)
    assert arslan._user_addressed_arslan("you answer this one") is False  # was True (over-match)
    assert arslan._user_addressed_arslan("研究X并直接回答所有子问题") is False
    # not addressing Arslan → no escape
    assert arslan._user_addressed_arslan("帮我做张 deck") is False
    assert arslan._user_addressed_arslan("让 Deck Master 做张 deck") is False
    assert arslan._user_addressed_arslan("") is False


# --------------------------------------------------------------------------- Fix 1: escape priority


@pytest.mark.asyncio
async def test_named_member_beats_escape_phrase(monkeypatch):
    """Fix 1a: an @named real member is an address to THAT member, checked BEFORE the escape
    hatch. `@ResearchAnalyst 直接回答:X` (Analyst is a member and the routed spawn) dispatches
    to the Analyst (cell 1), it does NOT get hijacked to Arslan self-answer (regression vs
    main, where the escape hatch was evaluated first)."""
    monkeypatch.setattr(arslan.roster_service, "is_member", lambda *a, **k: _aw(True))
    monkeypatch.setattr(arslan.router, "previous_decision", lambda conv: _aw(None))
    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", lambda sid: _aw("ResearchAnalyst"))
    answered, dispatched, frames = [], [], []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw(None))

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="@ResearchAnalyst 直接回答:调研一下 X")

    assert len(dispatched) == 1 and dispatched[0][0][1] == 7, "@member dispatches to the member"
    assert answered == [], "must NOT hijack to Arslan self-answer (escape hatch skipped)"


@pytest.mark.asyncio
async def test_inferred_task_text_with_answer_phrase_not_escape(monkeypatch):
    """Fix 1b: ordinary task text that merely CONTAINS '直接回答' (no @Arslan, no 你-anchor) must
    NOT trip the escape hatch. '研究X并直接回答' with a strong capable member routes to the
    member (cell 4) — Arslan does not self-answer."""
    _stub_arbitration_env(monkeypatch, is_member=True, ranked=[
        {"spawn_id": 7, "name": "Deck Master", "score": 0.9, "why": "strong"},
    ])
    answered, dispatched, frames = [], [], []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw(None))

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="研究X并直接回答所有子问题")

    assert len(dispatched) == 1 and dispatched[0][0][1] == 7, "routes to the member, not escape"
    assert answered == [], "did not fall into the escape hatch (Arslan self-answer)"


# --------------------------------------------------------------------------- Fix 2: lone picker


@pytest.mark.asyncio
async def test_lone_picker_member_answers_not_silent_dispatch(monkeypatch):
    """Fix 2: exactly ONE roster member in the picker band (moderate, 0.4≤score<0.8, below
    invite_one) must NOT be silently direct-dispatched. It falls to cell 7 — Arslan answers
    doer-first, NO card, NO dispatch. (Pre-fix: len(cands)>=2 False → returned MEMBER_DISPATCH,
    a silent direct dispatch that violated '直派只认强命中'.)"""
    _stub_arbitration_env(monkeypatch, is_member=True, ranked=[
        {"spawn_id": 7, "name": "Deck Master", "score": 0.5, "why": "moderate lone fit"},
    ])
    answered, dispatched, parked, chosen, frames = [], [], [], [], []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw("短答"))

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)
    monkeypatch.setattr(arslan.phase_service, "set_inviting",
                        lambda *a, **k: parked.append(k) or _aw(None))
    monkeypatch.setattr(arslan.phase_service, "set_choosing",
                        lambda *a, **k: chosen.append(k) or _aw(None))
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="帮我搞个演示")

    assert answered == [1], "lone picker-band member → Arslan answers doer-first (cell 7)"
    assert dispatched == [], "NO silent direct-dispatch of a lone moderate member"
    assert chosen == [], "no picker card parked (only ≥2 candidates pop a picker)"
    assert not any(f.get("type") in ("propose_invite", "clarify_options") for f in frames)


# --------------------------------------------------------------------------- Fix 3: invite_one B


@pytest.mark.asyncio
async def test_invite_one_dispatches_to_strong_top_not_router_pick(monkeypatch):
    """Fix 3: the router routed to member A (id 7) but the deterministic scorer's invite_one
    strong top is a DIFFERENT member B (id 8). Dispatch to B — trust the scorer, a strong
    capable member exists ('有对口成员就交给成员'). (Pre-fix: returned answer-only when
    pick != top, starving the turn.)"""
    _stub_arbitration_env(monkeypatch, is_member=True, ranked=[
        {"spawn_id": 8, "name": "Slide Smith", "score": 0.95, "why": "stronger fit"},
        {"spawn_id": 7, "name": "Deck Master", "score": 0.5, "why": "weaker"},
    ])
    answered, dispatched, frames = [], [], []
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: answered.append(1) or _aw(None))

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)

    await arslan._handle_route("main", _route_result(7), frames.append,
                               user_message="帮我搞个演示")

    assert len(dispatched) == 1, "a strong invite_one member exists → dispatch to it"
    assert dispatched[0][0][1] == 8, "dispatch to the scorer's strong top (B), not router's pick"
    assert answered == [], "Arslan does not self-answer — a capable member takes it"


# --------------------------------------------------------------------------- Fix 4: _match_choice


def test_match_choice_exact_and_short_fallback():
    """Fix 4: exact name still selects; a SHORT decorated echo still selects; a LONG unrelated
    message that merely CONTAINS a candidate name does NOT (returns None → the caller falls
    through to normal routing instead of auto-dispatching a stale parked choice)."""
    cands = [{"spawn_id": 7, "name": "Deck Master"}, {"spawn_id": 8, "name": "Slide Smith"}]
    assert arslan._match_choice("Deck Master", cands)["spawn_id"] == 7          # exact
    assert arslan._match_choice("deck master", cands)["spawn_id"] == 7          # case-normalized
    assert arslan._match_choice("选 Deck Master", cands)["spawn_id"] == 7       # short decorated echo
    # long unrelated message merely mentioning the name → no auto-dispatch
    long_msg = "帮我写一篇关于 Deck Master 这个产品的详细评测文章,要覆盖优缺点和竞品对比"
    assert arslan._match_choice(long_msg, cands) is None
    assert arslan._match_choice("", cands) is None


@pytest.mark.asyncio
async def test_choice_long_message_falls_through_no_dispatch(maker, monkeypatch):
    """Fix 4 (integration): with a parked picker choice, a LONG unrelated message that contains
    a candidate name must NOT auto-dispatch — the choice is cleared and the turn falls through
    to normal routing (here stubbed to `answer`)."""
    dispatched, answered, frames = [], [], []

    async def _disp(*a, **k):
        dispatched.append((a, k))
    monkeypatch.setattr(arslan, "dispatch_routed", _disp)
    monkeypatch.setattr(arslan.router, "route",
                        lambda conv, msg: _aw(arslan.router.RouterResult(action="answer")))
    monkeypatch.setattr(arslan, "_handle_answer",
                        lambda *a, **k: answered.append(1) or _aw(None))

    await phase_service.set_choosing(
        "main",
        candidates=[{"spawn_id": 7, "name": "Deck Master"},
                    {"spawn_id": 8, "name": "Slide Smith"}],
        task_brief="做半导体 PPT", user_message="帮我做半导体行业 PPT")

    await arslan.handle_user_message(
        "main", "帮我写一篇关于 Deck Master 这个产品的详细评测文章,要覆盖优缺点和竞品对比",
        frames.append)

    assert dispatched == [], "long unrelated message must NOT auto-dispatch the parked choice"
    assert answered == [1], "it falls through to normal routing (answer)"
    assert await phase_service.get_pending_choice("main") is None, "stale choice cleared"
