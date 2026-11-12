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

import errno
import os

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
        # The card opens as an asker opens it; the island on it, and its own reading alone (the card's rules left
        # out): both from the folder the waiting card keeps.
        card = approvals.open_card("c1", dict(request.frame), broadcast=False)
        try:
            requests.append((request, (approvals.island_may_answer(card.frame),
                                       approvals.island_may_answer({**card.frame, "rules": []}))))
        finally:
            approvals.close_card(card)
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
    assert approvals.CARD_FOLDER.get() is None                   # set only while the card is decided


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


def _card(call_id: str, elsewhere) -> dict:
    """A waiting command card with no rules on it, so the island's own reading decides."""
    return {"type": "propose_run_command", "call_id": call_id, "dedupe": "zz-dedupe", "perm_kind": "command",
            "pretty": f"cd {elsewhere} && rm {STAND_IN}"}


def _open(frame: dict, folder):
    token = approvals.CARD_FOLDER.set(folder)
    try:
        return approvals.open_card("c1", frame, broadcast=False)
    finally:
        approvals.CARD_FOLDER.reset(token)


@pytest.mark.parametrize("cwd, island", [(None, True), ("work", False)])
async def test_the_island_reads_the_cards_folder(folders, cwd, island):
    """The island's own reading of a waiting card, outside the run: from the folder the card keeps, else as before."""
    work, elsewhere = folders
    pending = _open(_card("zz-call", elsewhere), work if cwd else None)
    try:
        assert approvals.island_may_answer(pending.frame) is island
    finally:
        approvals.close_card(pending)


async def test_a_joined_card_keeps_its_folder_until_its_last_waiter_leaves(folders):
    """#872 review B3: two waiters on one card; the first leaves, and the island still reads the card's folder."""
    work, elsewhere = folders
    first = _open(_card("zz-first", elsewhere), work)
    second = _open(_card("zz-second", elsewhere), work)
    assert second is first and first.waiters == 2                   # joined: one card, the first one's id
    approvals.close_card(first)                                     # the first waiter leaves
    assert approvals.card_folder(first.frame) == work
    assert approvals.island_may_answer(first.frame) is False
    approvals.close_card(second)                                    # the last waiter: the card is gone
    assert approvals.card_folder(first.frame) is None


async def test_the_same_command_from_two_folders_makes_two_cards(folders):
    """#872 review B3: a request from another run folder never joins a waiting card."""
    work, elsewhere = folders
    one = _open(_card("zz-one", elsewhere), work)
    two = _open(_card("zz-two", elsewhere), work / "sub")
    try:
        assert two is not one and (one.folder, two.folder) == (work, work / "sub")
    finally:
        approvals.close_card(one)
        approvals.close_card(two)


# ── #872 review B1: a change of folder the reader can't follow, from a known starting folder ─────────────────────

@pytest.mark.parametrize("command, rule", [
    (f'cd "$ZZ_STAND_IN" && rm {STAND_IN}', "delete-outside"),
    (f"cd - && rm {STAND_IN}", "delete-outside"),
    (f'cd "$ZZ_STAND_IN" && touch {STAND_IN}', "protected-write"),
    (f'cd "$ZZ_STAND_IN" && echo x > {STAND_IN}', "protected-write"),
])
def test_an_unknown_folder_after_a_move_asks(folders, command, rule):
    work, _elsewhere = folders
    assert rule in tp.ask_rules(command, cwd=work)
    assert rule not in tp.ask_rules(command)                       # no starting folder: as on main


def test_an_unknown_move_then_an_absolute_path_reads_as_before(folders):
    work, elsewhere = folders
    command = f'cd "$ZZ_STAND_IN" && touch {elsewhere / STAND_IN}'
    assert tp.assess(command, cwd=work) == tp.assess(command)


def test_a_literal_move_inside_still_runs(folders):
    work, _elsewhere = folders
    assert tp.assess(f"cd sub && rm {STAND_IN}", cwd=work).level == "run"


# ── #872 review B2: a relative path through a link to a folder outside ─────────────────────────────────────────

@pytest.fixture
def linked(folders):
    work, elsewhere = folders
    (work / "zz-link").symlink_to(elsewhere, target_is_directory=True)
    return work


@pytest.mark.parametrize("command", [
    f"rm zz-link/{STAND_IN}", f"cd zz-link && rm {STAND_IN}", "rm -r zz-link/", "find zz-link/ -delete"])
def test_a_relative_path_through_a_link_out_asks(linked, command):
    assert "delete-outside" in tp.ask_rules(command, cwd=linked)
    assert tp.ask_rules(command) == set()                          # no starting folder: as on main


@pytest.mark.parametrize("command", ["rm zz-link", f"rm sub/{STAND_IN}", f"cd sub && rm {STAND_IN}"])
def test_the_link_itself_and_real_folders_inside_run(linked, command):
    assert tp.assess(command, cwd=linked).level == "run"


@pytest.mark.parametrize("failure", ["anchor", "parent-metadata"])
def test_resolution_failure_does_not_allow_outside_delete(linked, failure, monkeypatch):
    """Review delta 2: with the link out in place, a failure to resolve the given working folder, or a metadata error
    on the way to the target's folder (one a realpath that isn't strict swallows), asks; it never lets the delete
    through. The failures are injected (PermissionError), never made with real permissions."""
    real_realpath, real_lstat = os.path.realpath, os.lstat
    link = os.path.join(real_realpath(linked), "zz-link")

    def realpath(path, *, strict=False):
        if os.fspath(path) == str(linked):
            raise PermissionError(errno.EACCES, "stand-in")
        return real_realpath(path, strict=strict)

    def lstat(path, *args, **kwargs):
        if os.fspath(path) == link:
            raise PermissionError(errno.EACCES, "stand-in")
        return real_lstat(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        if failure == "anchor":
            patch.setattr(os.path, "realpath", realpath)
        else:
            patch.setattr(os, "lstat", lstat)
        rules = tp.ask_rules(f"rm zz-link/{STAND_IN}", cwd=linked)
    assert "delete-outside" in rules


def test_a_card_folder_is_none_with_no_waiting_card(folders):
    """Review delta 2 (B3): a frame with no waiting card has no folder, whatever this run's folder is."""
    work, elsewhere = folders
    token = approvals.CARD_FOLDER.set(work)
    try:
        assert approvals.card_folder(_card("zz-no-card", elsewhere)) is None
        assert approvals.card_folder({}) is None
    finally:
        approvals.CARD_FOLDER.reset(token)


async def test_a_folder_that_cannot_be_read_is_none(monkeypatch):
    async def broken(db):
        raise OSError("stand-in")
    monkeypatch.setattr(settings_service, "workspace_dir_for_run", broken)
    assert await command_gate.run_folder() is None
