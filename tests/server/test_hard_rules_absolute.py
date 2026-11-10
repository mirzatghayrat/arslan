"""HR-0, the absolute list (hard_rules.ABSOLUTE): what holds whatever the settings. Each test runs under every entry of
`SETTINGS`, today the least strict ones main has: "Ask only for risky commands", this conversation's grant to run
commands outside the sandbox, and the sandbox switched off. S5a adds full access as a second entry.

Commands never run here: the subprocess is replaced, and the profile it would have started under is what is read
(as on a Mac, where seatbelt can start; CI's Linux has none). Command texts come from the existing tests' own cases."""
from __future__ import annotations

import pytest

from server.orchestrator import tool_loop, untrusted
from server.services import (approvals, command_sandbox, permission_store, permissions, sandbox_profile,
                             settings_service, terminal_exec)
from tests.server import hard_rules_cases as hr

CONV = "c1"
STAND_IN = "zz-stand-in-word"
_THREE = "tests/server/test_s2a2_three_layers.py::"

#: The settings each absolute rule is tested under. S5a: add "full_access" here (and how to switch it on in `loosest`).
SETTINGS = {
    "least_strict": {"shell_confirm_policy": "ask_risky", "terminal_sandbox_enabled": "false", "outside_grant": True},
}


@pytest.fixture(params=sorted(SETTINGS))
async def loosest(request, execution_db, monkeypatch):
    chosen = SETTINGS[request.param]
    async with execution_db() as db:
        await settings_service.update_settings(db, {k: v for k, v in chosen.items() if k != "outside_grant"})
        if chosen["outside_grant"]:
            await permission_store.add_grant(db, CONV, "", "outside", "*", call_id="card-1")
            await db.commit()
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    yield request.param
    command_sandbox._reset_for_tests()


class _Surface:
    """The turn's card surface (a stored grant stands only where one is): records each card, answers `approve`."""

    def __init__(self, approve=False):
        self.frames, self.approve = [], approve

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": self.approve, "scope": "once", "by": "user", "call_id": frame["call_id"]}


async def _run(monkeypatch, command, *, approve_card=False, surface=None, **args):
    """The tool loop and the real run_command executor, up to the subprocess: (cards shown, the argv it would start)."""
    started, cards = [], []

    async def fake_exec(*argv, **kwargs):
        started.append(argv)
        raise RuntimeError("not run")

    async def card(command, argv, **kw):
        cards.append(kw)
        return approve_card

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    monkeypatch.setattr(terminal_exec.asyncio, "create_subprocess_exec", fake_exec)
    trace: list = []
    with permissions.asking_with(surface or _Surface()):
        await tool_loop._dispatch_tool("run_command", {"command": command, **args}, "{}", resolve_tools=resolve,
                                       emit=lambda e: None, tool_timeout_s=5, tool_trace=trace, convo=[],
                                       confirm_command=card, conversation_id=CONV)
    return cards, started, trace


def _profile(started) -> str:
    [argv] = started
    assert argv[0] == "/usr/bin/sandbox-exec", argv[:1]            # never with no wrapper
    return argv[2]


def _denied(profile: str, paths) -> bool:
    lines = [line for line in profile.splitlines() if line.startswith("(deny file-read* file-write*")]
    return all(any(sandbox_profile.file_or_folder(p) in line for line in lines) for p in paths)


async def test_the_floor_refuses_before_any_card(loosest, monkeypatch):
    texts = {c["rule"]: c["command"] for c in reversed(hr.cases(_THREE + "test_every_forbid_rule_refuses"))}
    texts["trash"] = hr.first_command(
        "tests/server/test_smart8_delete_to_trash.py::test_a_delete_from_the_trash_or_emptying_it_is_forbidden")
    for rule, text in texts.items():
        cards, started, trace = await _run(monkeypatch, text, approve_card=True, outside_sandbox=True, why="w")
        assert (cards, started) == ([], []) and "never runs" in str(trace[-1]), rule


async def test_arslans_own_data_stays_closed(loosest, monkeypatch):
    cards, started, _ = await _run(monkeypatch, STAND_IN)
    assert cards == [] and _denied(_profile(started), command_sandbox.arslan_protected())


async def test_the_skill_and_plugin_folders_stay_closed(loosest, monkeypatch):
    _, started, _ = await _run(monkeypatch, STAND_IN)
    assert _denied(_profile(started), command_sandbox.cap6b_folders())


async def test_apple_events_stay_refused(loosest, monkeypatch):
    """Refused by the profile; an Apple Events command still asks under the grant, and a yes that was not the
    asking window's own click keeps it wrapped (only U11's bare run sends them)."""
    _, started, _ = await _run(monkeypatch, STAND_IN)
    assert "(deny appleevent-send)" in _profile(started).splitlines()
    text = hr.first_command(_THREE + "test_layer_two_asks_this_time_only", "apple-events")
    cards, started, _ = await _run(monkeypatch, text, approve_card=False)
    assert len(cards) == 1 and started == []
    approvals.LAST_OUTCOME.set(None)
    cards, started, _ = await _run(monkeypatch, text, approve_card=True)
    assert len(cards) == 1 and "(deny appleevent-send)" in _profile(started).splitlines()


async def test_after_outside_content_it_runs_offline_and_the_network_asks(loosest, monkeypatch):
    seen = untrusted.track_turn()
    untrusted.mark_external()
    try:
        _, started, _ = await _run(monkeypatch, STAND_IN)
        assert "(deny network*)" in _profile(started).splitlines()
        surface = _Surface(approve=False)
        cards, started, _ = await _run(monkeypatch, STAND_IN, surface=surface, network=True, why="w")
    finally:
        untrusted.end_turn(seen)
    assert [f["perm_kind"] for f in surface.frames] == ["network"] and surface.frames[0]["options"] == ["once"]
    assert started == [] and not approvals.island_may_answer(surface.frames[0])


async def test_money_is_a_card_every_time(loosest, execution_db):
    async with execution_db() as db:
        await permission_store.add_rule(db, "money", STAND_IN)
        await permission_store.add_grant(db, CONV, "", "money", STAND_IN)
        await db.commit()
    surface = _Surface(approve=True)
    pay = permissions.Request(kind="money", target=STAND_IN, title=STAND_IN)
    with permissions.asking_with(surface):
        for _ in range(2):
            assert (await permissions.decide(pay, permissions.Context(CONV))).by == "user"
    assert [f["options"] for f in surface.frames] == [["once"], ["once"]]


async def test_a_capability_is_answered_in_the_asking_window_only(loosest, execution_db):
    async with execution_db() as db:
        await permission_store.add_grant(db, CONV, "", "capability", STAND_IN)
        await db.commit()
    surface = _Surface(approve=False)
    with permissions.asking_with(surface):
        decision = await permissions.decide(permissions.Request(kind="capability", target=STAND_IN, title=STAND_IN),
                                            permissions.Context(CONV))
    [frame] = surface.frames                                      # the grant answered nothing
    assert not decision.allowed and frame["options"] == ["once"]
    assert approvals.window_only(frame) and not approvals.island_may_answer(frame)
