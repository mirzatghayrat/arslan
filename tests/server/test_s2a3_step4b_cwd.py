"""S2a-3 step 4b: the command policy follows a change of folder from the run's real working folder.

Step 4 (#789) taught `terminal_policy.assess` and `ask_rules` to take `cwd`; here the gate (`command_gate.check`), the
command's card (`command_confirm`) and the island (`approvals.island_may_answer`) pass it, the folder read as the
executor reads it (`settings_service.workspace_dir_for_run`). Under "ask for risky commands", with this conversation's
grant to leave the sandbox, a change of folder out of the working folder followed by a relative delete asks
`delete-outside` instead of running with no card (#406's gap, ASK1-a's #871). The same command into a folder inside
the working folder runs as before, and with no folder known nothing changes.

Stand-ins only: a plain `cd` and an `rm` of a stand-in name, in tmp folders; nothing runs (the gate is asked, never
the executor)."""
from __future__ import annotations

import pytest

from server.orchestrator import command_gate, untrusted
from server.orchestrator.turn_state import ToolTurn
from server.services import approvals, command_confirm, command_sandbox, permissions, settings_service
from server.services import terminal_policy as tp

STAND_IN = "zz-stand-in-word"


@pytest.fixture
def folders(tmp_path):
    work, elsewhere = tmp_path / "work", tmp_path / "elsewhere"
    (work / "sub").mkdir(parents=True)
    elsewhere.mkdir()
    return work, elsewhere


@pytest.fixture
def risky_with_grant(monkeypatch):
    """Ask for risky commands, the sandbox on, and this conversation's stored grant to leave it."""
    async def answer(value):
        return value
    monkeypatch.setattr(command_gate, "_sandbox_enabled", lambda: answer(True))
    monkeypatch.setattr(command_gate, "_asks_for_everything", lambda: answer(False))
    monkeypatch.setattr(command_gate, "_outside_grant", lambda conversation_id, command: answer(object()))
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(settings_service, "shell_confirm_policy", lambda db: answer("ask_risky"))


def _work_folder(monkeypatch, folder):
    async def for_run(db):
        return folder
    monkeypatch.setattr(settings_service, "workspace_dir_for_run", for_run)


async def _check(command: str, confirm_command):
    turn = untrusted.track_turn()                          # a turn that has read nothing from outside
    try:
        return await command_gate.check("run_command", {"command": command}, ToolTurn(
            resolve_tools=None, emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
            confirm_command=confirm_command, conversation_id="c1"))
    finally:
        untrusted.end_turn(turn)


@pytest.fixture
def shown(monkeypatch):
    """The real card (`command_confirm`), its decision replaced by a no: what it would show, and nothing runs. The
    island is asked while the card waits, as the island page asks."""
    requests: list = []

    async def decide(request, context):
        # The island on the card, and its own reading alone (the card's rules left out): both from the run's folder.
        requests.append((request, (approvals.island_may_answer(request.frame),
                                   approvals.island_may_answer({**request.frame, "rules": []}))))
        return permissions.Decision(False, "user", "once")
    monkeypatch.setattr(permissions, "decide", decide)
    return requests


async def test_a_change_of_folder_out_of_the_working_folder_asks_delete_outside(folders, risky_with_grant, shown,
                                                                                 monkeypatch):
    work, elsewhere = folders
    _work_folder(monkeypatch, work)
    command = f"cd {elsewhere} && rm {STAND_IN}"
    result = await _check(command, command_confirm.Confirmations("c1").command)
    assert isinstance(result, dict) and result["ok"] is False, result        # a card, answered no: not a run
    assert len(shown) == 1
    (request, island), = shown
    assert "delete-outside" in request.frame["rules"]            # the card's rules agree with the gate's verdict
    assert island == (False, False)                              # and the island, asked while it waits, agrees
    assert approvals.CARD_FOLDERS == {}                          # held only while the card waits


async def test_the_card_frame_keys_are_unchanged(folders, risky_with_grant, shown, monkeypatch):
    """No folder key on the frame (not a Bridge frame change): a card that asks the same with a folder and with none
    (main's reading) has the same keys."""
    work, elsewhere = folders
    command = f"rm {elsewhere / STAND_IN}"
    keys = []
    for folder in (None, work):
        _work_folder(monkeypatch, folder)
        await command_confirm.Confirmations("c1").command(command, [])
        keys.append(set(shown[-1][0].frame))
    assert keys[0] == keys[1] and "cwd" not in keys[1]


async def test_the_same_command_into_a_folder_inside_runs_as_before(folders, risky_with_grant, shown, monkeypatch):
    work, _elsewhere = folders
    _work_folder(monkeypatch, work)
    plan = await _check(f"cd sub && rm {STAND_IN}", command_confirm.Confirmations("c1").command)
    assert isinstance(plan, command_gate.CommandPlan) and plan.run_outside and plan.by_grant, plan
    assert shown == [] and not plan.deletes_outside


async def test_with_no_folder_known_it_reads_as_before(folders, risky_with_grant, shown, monkeypatch):
    """`workspace_dir_for_run` None (no workspace): the text alone, as before step 4b; the executor refuses that run."""
    _work_folder(monkeypatch, None)
    _work, elsewhere = folders
    plan = await _check(f"cd {elsewhere} && rm {STAND_IN}", command_confirm.Confirmations("c1").command)
    assert isinstance(plan, command_gate.CommandPlan) and shown == []


async def test_the_gate_card_and_island_read_one_folder(folders, risky_with_grant, monkeypatch):
    """The folder the gate read is the one the card's callback and the island read: one `run_folder`."""
    work, elsewhere = folders
    _work_folder(monkeypatch, work)
    assert await command_gate.run_folder() == work
    command = f"cd {elsewhere} && rm {STAND_IN}"
    assert tp.ask_rules(command, cwd=work) == {"delete-outside"} and tp.ask_rules(command) == set()


@pytest.mark.parametrize("cwd, island", [(None, True), ("work", False)])
def test_the_island_reads_the_cards_folder(folders, cwd, island, monkeypatch):
    """The island's own reading of a card with no rules on it: from the folder held for the waiting card, else as
    before."""
    work, elsewhere = folders
    if cwd:
        monkeypatch.setitem(approvals.CARD_FOLDERS, "zz-call", work)
    frame = {"type": "propose_run_command", "call_id": "zz-call", "pretty": f"cd {elsewhere} && rm {STAND_IN}",
             "perm_kind": "command"}
    assert approvals.island_may_answer(frame) is island


async def test_a_folder_that_cannot_be_read_is_none(monkeypatch):
    async def broken(db):
        raise OSError("stand-in")
    monkeypatch.setattr(settings_service, "workspace_dir_for_run", broken)
    assert await command_gate.run_folder() is None
