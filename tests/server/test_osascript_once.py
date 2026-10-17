"""0.1.62 F4a (R2): osascript and `shortcuts run` through the terminal are recognised however
they are written (a path, `command`, `exec`, `xargs`), and their card is for this time only:
no "In this conversation", no "Always", and no answer stored before it lets one through."""
from unittest.mock import AsyncMock

import pytest

from server.services import approvals, permissions, run_registry
from server.services import terminal_policy as tp
from tests.server.test_background_jobs import CID, _declining
from tests.server.test_run_command_confirm_flow import (_collect_until, _enable_shell,
                                                        _stub_run_command_executor, _stub_tool_loop_adapter,
                                                        app_client)  # noqa: F401 — a fixture

OSA = "-e 'tell application \"Finder\" to activate'"
SPELLINGS = [
    (f"osascript {OSA}", "apple-events"),
    (f"/usr/bin/osascript {OSA}", "apple-events"),
    (f"command osascript {OSA}", "apple-events"),
    ("echo x | xargs osascript", "apple-events"),
    ("printf 'a\\0' | xargs -0 osascript", "apple-events"),
    ("ls *.scpt | xargs -I {} osascript {}", "apple-events"),
    ("ls *.scpt | xargs -n 1 osascript", "apple-events"),
    (f"exec /usr/bin/osascript {OSA}", "apple-events"),
    (f"command /usr/bin/osascript {OSA}", "apple-events"),
    ('shortcuts run "Send note"', "shortcuts"),
    ('/usr/bin/shortcuts run "Send note"', "shortcuts"),
    ('command shortcuts run "Send note"', "shortcuts"),
]


@pytest.mark.parametrize("command,rule", SPELLINGS)
def test_every_spelling_is_recognised(command, rule):
    verdict = tp.assess(command)
    assert verdict.level == "ask" and verdict.rule == rule, verdict


def test_inside_a_shell_string_too():
    assert "apple-events" in tp.ask_rules(f'zsh -c "/usr/bin/osascript {OSA}"')


@pytest.mark.parametrize("command", ['echo "use osascript"', "grep -r osascript .", "cat shortcuts.txt",
                                     "command -v osascript"])
def test_a_mention_is_not_a_run(command):
    assert tp.assess(command).level == "run"


@pytest.mark.parametrize("command,rule", SPELLINGS)
def test_the_card_is_for_this_time_only(command, rule):
    req = approvals._command_request(command, sorted(tp.ask_rules(command)), None)
    assert req.once_only is True
    assert permissions.options_for(req) == ["once"]
    assert req.remember_as == () and req.always_label == ""      # the Inbox's "Always allow" stores nothing


def test_a_remembered_rule_no_longer_lets_it_through():
    assert not tp.standing_allows(f"osascript {OSA}", {"apple-events"})
    assert not tp.standing_allows('shortcuts run "x"', {"shortcuts"})
    assert tp.standing_allows("brew install x", {"install"})          # other rules keep their "Always"


def test_a_once_only_ask_never_shares_a_card_with_one_that_is_not():
    import dataclasses
    once = approvals._command_request("osascript x", ["apple-events"], None)
    assert permissions._dedupe(once) != permissions._dedupe(dataclasses.replace(once, once_only=False))


async def test_a_jobs_card_offers_only_this_time(execution_db, monkeypatch):
    from server.services import settings_service
    monkeypatch.setattr(settings_service, "shell_confirm_policy", AsyncMock(return_value="ask_risky"))
    monkeypatch.setattr(tp, "always_allowed", AsyncMock(return_value={"apple-events"}))
    asked = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: _declining(asked, "options"))
    confirm = approvals.JobConfirmations(CID)
    assert await confirm.command(f"/usr/bin/osascript {OSA}", []) is False   # remembered, still asked
    assert asked == [["once"]]


def test_the_windows_card_offers_only_this_time_despite_a_rule_and_a_grant(app_client, monkeypatch):  # noqa: F811
    from server.services import permission_store
    _enable_shell(app_client, policy="ask_risky")

    async def remember():
        async with app_client.db_maker() as db:
            await tp.allow_always(db, "apple-events")
            await permission_store.add_grant(db, "osa", "", "command", "rules:apple-events")
            await db.commit()
    app_client.portal.call(remember)
    for command in (f"osascript {OSA}", f"/usr/bin/osascript {OSA}"):
        _stub_tool_loop_adapter(monkeypatch, command, [])
        executor = _stub_run_command_executor(monkeypatch)
        with app_client.websocket_connect("/ws/arslan/osa") as ws:
            ws.receive_json()
            ws.send_json({"type": "user_message", "content": "tell Finder"})
            frames = _collect_until(ws, "propose_run_command")
            assert frames[-1]["type"] == "propose_run_command", [f["type"] for f in frames]
            assert frames[-1]["options"] == ["once"]
            ws.send_json({"type": "cancel_run_command", "call_id": frames[-1]["call_id"]})
            _collect_until(ws, "stream_end")
        assert executor.calls == []
