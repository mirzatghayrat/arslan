"""Routing announcement (@-mention brief) + auto-continue on digest-fallback rounds.

Style: test_confirm_guards — monkeypatched adapters/services, no LLM, no live loop.

1. The routing announcement restates the need and @-mentions each involved spawn,
   grounded in the REAL roster (never invented names); a clearly-implied second stage
   (e.g. 生成PPT → the deck spawn) is mentioned as 可能接力.
2. A dispatch round ending with a 【阶段性发现】digest auto-re-dispatches the same
   spawn (bounded by MAX_AUTO_CONTINUES, threaded — no module-global state); the bare
   no-evidence fallback never re-dispatches.
"""
from types import SimpleNamespace

import pytest

from server.orchestrator import arslan

pytestmark = pytest.mark.asyncio


def _spawn(sid, name, domain="research", sub=None, caps=None, role=""):
    return SimpleNamespace(
        id=sid, name=name, domain_category=domain, domain_subcategory=sub,
        capabilities=caps or [], persona_role=role,
    )


# ── 1. routing announcement ────────────────────────────────────────────────────


async def test_announcement_mentions_primary_and_second_stage(monkeypatch):
    """OKX调研+生成PPT → @primary 负责… plus the real deck spawn as 可能接力."""
    spawns = [
        _spawn(7, "调研员", domain="finance", caps=["市场调研"], role="加密市场研究员"),
        _spawn(9, "Deck Master", domain="creative", sub="presentation",
               caps=["PPT design"], role="演示文稿专家"),
    ]

    async def _all():
        return spawns

    async def _roster(cid):
        return [{"spawn_id": 7, "spawn_name": "调研员"},
                {"spawn_id": 9, "spawn_name": "Deck Master"}]

    monkeypatch.setattr(arslan.spawn_service, "load_all_spawns", _all)
    monkeypatch.setattr(arslan.roster_service, "list_roster", _roster)

    text = await arslan._route_announcement(
        "conv", 7, "调研员", "用户需要加密货币交易所(OKX)的永续合约调研,并生成PPT")

    assert "用户需要加密货币交易所(OKX)的永续合约调研" in text  # need restated
    assert "@调研员" in text and "负责" in text                  # primary @-mention
    assert "@Deck Master" in text and "可能接力" in text         # real second stage
    # grounded: only real roster names are mentioned
    for token in text.split():
        if token.startswith("@"):
            assert token.lstrip("@").startswith(("调研员", "Deck"))


async def test_announcement_single_spawn_one_line_no_invented_names(monkeypatch):
    """No second stage implied → exactly one @-mention (the primary), nothing invented."""
    spawns = [
        _spawn(7, "调研员", domain="finance", caps=["市场调研"]),
        _spawn(9, "Deck Master", domain="creative", sub="presentation", caps=["PPT design"]),
    ]

    async def _all():
        return spawns

    async def _roster(cid):
        return [{"spawn_id": 7, "spawn_name": "调研员"}]

    monkeypatch.setattr(arslan.spawn_service, "load_all_spawns", _all)
    monkeypatch.setattr(arslan.roster_service, "list_roster", _roster)

    text = await arslan._route_announcement("conv", 7, "调研员", "调研OKX永续合约市场")
    assert text.count("@") == 1
    assert "@调研员" in text
    assert "Deck Master" not in text  # no PPT implied → deck spawn not dragged in


async def test_announcement_survives_service_failure(monkeypatch):
    """Enrichment (roles / second stage) is best-effort: a DB failure still yields
    the need + the primary @-mention, never an exception up the dispatch path."""
    async def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(arslan.spawn_service, "load_all_spawns", _boom)

    text = await arslan._route_announcement("conv", 7, "调研员", "查一下OKX的合约数量")
    assert "@调研员" in text and "负责" in text
    assert "查一下OKX的合约数量" in text


def test_second_stage_matcher_is_grounded():
    """The deterministic matcher only ever returns a spawn from the given list."""
    spawns = [
        _spawn(9, "Deck Master", domain="creative", sub="presentation", caps=["PPT design"]),
        _spawn(11, "Writer", domain="content", caps=["copywriting"]),
    ]
    hit = arslan._find_second_stage("调研并生成PPT汇报", spawns, primary_id=7, roster_ids={9})
    assert hit is spawns[0]
    miss = arslan._find_second_stage("写一篇小红书文案", spawns, primary_id=7, roster_ids=set())
    assert miss is None


# ── 2. auto-continue on digest-ending rounds ───────────────────────────────────

_DIGEST_TAIL = ("【阶段性发现】(本轮已查到的资料,尚未成稿)\n- web_search(OKX): …\n\n"
                "这个任务这一轮还没做完。回复“继续”我就接着做。")
_BARE_FALLBACK = "这个任务这一轮还没做完。回复“继续”我就接着做;也可以把范围缩小一点,会更快。"
_CLEAN = "# OKX 调研报告\n完整成稿。"


class _FakeRecorder:
    run_id = 1

    @classmethod
    async def start(cls, **kw):
        return cls()

    def tee(self, emit):
        return emit

    async def finalize(self, **kw):
        return None


def _wire_dispatch(monkeypatch, outputs):
    """Stub every _dispatch_spawn dependency; returns the list of dispatch calls.
    `outputs[i]` is the full_output of the i-th dispatch (last one repeats)."""
    calls = []

    async def _name(spawn_id):
        return "Researcher"

    async def _join(cid, sid, *, via):
        return False

    async def _roster(cid):
        return []

    async def _announce(cid, sid, name, brief):
        return f"@{name} — 负责:执行这项任务"

    async def _dispatch(conv, *, spawn_id, task_brief, **kw):
        calls.append(task_brief)
        out = outputs[min(len(calls) - 1, len(outputs) - 1)]
        return {"full_output": out, "spawn_name": "Researcher",
                "summary_message_id": 100 + len(calls),
                "assistant_message_id": 200 + len(calls), "escalation": None}

    monkeypatch.setattr(arslan.dispatcher, "get_spawn_name", _name)
    monkeypatch.setattr(arslan.roster_service, "join", _join)
    monkeypatch.setattr(arslan.roster_service, "list_roster", _roster)
    monkeypatch.setattr(arslan, "_route_announcement", _announce)
    monkeypatch.setattr(arslan.dispatcher, "dispatch", _dispatch)
    monkeypatch.setattr(arslan.run_recorder, "RunRecorder", _FakeRecorder)
    return calls


async def test_digest_round_triggers_exactly_one_recontinue(monkeypatch):
    """Round 1 ends with a digest → ONE automatic re-dispatch (same spawn, same
    direction); round 2 is clean → stop. The digest message is emitted first."""
    calls = _wire_dispatch(monkeypatch, [_DIGEST_TAIL, _CLEAN])
    events = []
    await arslan._dispatch_spawn("conv", 7, "调研OKX", events.append, user_message="调研OKX")

    assert calls == ["调研OKX", "调研OKX"]                     # exactly one re-dispatch
    types = [e["type"] for e in events]
    assert types.count("auto_continue") == 1
    assert types.count("stream_end") == 2                      # digest round + clean round
    # the digest round's message reached the user BEFORE the continuation started
    assert types.index("stream_end") < types.index("auto_continue")
    # the continuation re-emits routing (UI pulse continues) but no second announcement
    routing_frames = [e for e in events if e["type"] == "routing"]
    assert len(routing_frames) == 2
    assert "announcement" in routing_frames[0]
    assert "announcement" not in routing_frames[1]


async def test_auto_continue_caps_at_two_and_keeps_final_digest(monkeypatch):
    """Every round ends with a digest → 1 + MAX_AUTO_CONTINUES dispatches total; the
    final digest message (with its now-honest 回复'继续' tail) is preserved."""
    calls = _wire_dispatch(monkeypatch, [_DIGEST_TAIL])       # digest forever
    events = []
    await arslan._dispatch_spawn("conv", 7, "调研OKX", events.append, user_message="调研OKX")

    assert len(calls) == 1 + arslan.MAX_AUTO_CONTINUES == 3
    types = [e["type"] for e in events]
    assert types.count("auto_continue") == arslan.MAX_AUTO_CONTINUES
    assert types.count("stream_end") == 3
    # the last round's stream_end is the final frame — its digest message stands as-is
    assert types[-1] == "stream_end"


async def test_bare_fallback_never_auto_continues(monkeypatch):
    """The no-evidence fallback (no digest marker) made zero progress — looping on it
    would burn tokens for nothing. It must NOT re-dispatch."""
    calls = _wire_dispatch(monkeypatch, [_BARE_FALLBACK])
    events = []
    await arslan._dispatch_spawn("conv", 7, "调研OKX", events.append, user_message="调研OKX")

    assert len(calls) == 1
    assert not any(e["type"] == "auto_continue" for e in events)


async def test_clean_round_never_auto_continues(monkeypatch):
    calls = _wire_dispatch(monkeypatch, [_CLEAN])
    events = []
    await arslan._dispatch_spawn("conv", 7, "调研OKX", events.append, user_message="调研OKX")
    assert len(calls) == 1
    assert not any(e["type"] == "auto_continue" for e in events)


def test_digest_marker_detection():
    assert arslan._has_findings_digest(_DIGEST_TAIL)
    assert arslan._has_findings_digest("[Findings so far] (gathered this round)\n- x")
    assert not arslan._has_findings_digest(_BARE_FALLBACK)
    assert not arslan._has_findings_digest("")
    assert not arslan._has_findings_digest(None)
