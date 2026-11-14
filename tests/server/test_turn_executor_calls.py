"""What reaches a tool's executor through a whole turn (`run_native`): its arguments, what the turn sets around the
call (who calls, offline, outside the sandbox, no wrapper, deletes to the Trash), the card shown on the way with what it
shows, and the call's time limit. Each gate has its own tests; these check that what the gates decide reaches the call."""
import pytest

from server.orchestrator import tool_caller
from server.services import terminal_exec
from tests.server.scripted_turn import (  # noqa: F401 — the fixtures
    Reply,
    Turn,
    batch,
    booted_db_fixture,
    call,
    card,
    run_turn,
    table,
    turn_db_fixture,
    writes_need_a_card,
)

CLEAR = {"offline": False, "outside": False, "unwrapped": False, "trash": False, "caller": None, "model": "_Model"}


def _command(turn, **own):
    return dict(tools=table("run_command"), confirm_command=card(turn, "command", **own))


async def test_every_card_and_keyword_reaches_the_call(monkeypatch, turn_db):
    """Each card shows what the call will do, the caller and the turn's own tool limit reach every executor."""
    turn = Turn()
    writes_need_a_card(monkeypatch)
    replies = [batch(("write_file", {"path": "a.md", "content": "x"}, "c1"),
                     ("schedule_task", {"name": "n", "when": "every: 3600", "prompt": "p"}, "c2"),
                     ("run_command", {"command": "git push origin main", "why": "to publish it"}, "c3")),
               Reply("Done.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=table("write_file", "schedule_task", "run_command"),
                   confirm_command=card(turn, "command"), confirm_workspace_write=card(turn, "write"),
                   confirm_schedule=card(turn, "schedule"), tool_timeout_s=7.5, conversation_id="c1",
                   caller=tool_caller.ToolCaller("host", None, "c1"))
    assert turn.cards == [("write", ["write_file", "a.md"], {}), ("schedule", ["n", "every: 3600"], {"prompt": "p"}),
                          ("command", ["git push origin main", []], {"why": "to publish it"})]
    assert [(tool, args) for tool, args, _ in turn.ran] == [
        ("write_file", {"path": "a.md", "content": "x"}),
        ("schedule_task", {"name": "n", "when": "every: 3600", "prompt": "p"}),
        ("run_command", {"command": "git push origin main", "why": "to publish it"})]
    assert all(around == {**CLEAR, "caller": "host"} for _tool, _args, around in turn.ran)
    assert turn.limits == [7.5, 7.5, 7.5]
    # each card comes before its own call, and the next call's card after it
    assert [entry for entry in turn.log if entry.startswith(("card:", "ran:"))] == [
        "card:write", "ran:write_file", "card:schedule", "ran:schedule_task", "card:command", "ran:run_command"]


async def test_a_command_outside_the_sandbox(monkeypatch, turn_db):
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [call("run_command", {"command": "ls", "outside_sandbox": True,
                                                                     "why": "it needs the keychain"}), Reply("Done.")],
                   **_command(turn))
    assert turn.cards == [("command", ["ls", []], {"sandbox": "outside", "why": "it needs the keychain"})]
    assert turn.ran[0][2] == {**CLEAR, "outside": True}


async def test_a_command_the_sandbox_stopped_goes_outside_on_its_second_card(monkeypatch, turn_db):
    turn = Turn()

    def stopped(_args):
        if terminal_exec.OUTSIDE_SANDBOX.get():
            return {"ok": True, "exit_code": 0, "stdout": "done"}
        return {"ok": False, "sandbox_denied": True, "error": "the sandbox stopped it"}
    replies = [call("run_command", {"command": "ls"}, "c1"),
               call("run_command", {"command": "ls", "outside_sandbox": True, "why": "the sandbox stopped it"}, "c2"),
               Reply("Done.")]
    await run_turn(turn, monkeypatch, turn_db, replies, answers={"run_command": stopped}, **_command(turn))
    assert [around["outside"] for _tool, _args, around in turn.ran] == [False, True]
    assert [frame["summary"] for frame in turn.results()][0] == "the sandbox stopped it"
    assert turn.cards[1] == ("command", ["ls", []], {"sandbox": "outside", "why": "the sandbox stopped it"})


async def test_a_plain_script_the_user_clicked_runs_with_no_wrapper(monkeypatch, turn_db):
    turn = Turn()
    script = "osascript -e 'tell application \"Notes\" to count notes'"
    await run_turn(turn, monkeypatch, turn_db, [call("run_command", {"command": script}), Reply("Done.")],
                   **_command(turn, clicked=True))
    assert turn.cards == [("command", [script, []], {})]
    assert turn.ran[0][2] == {**CLEAR, "outside": True, "unwrapped": True}


@pytest.mark.usefixtures("s2a1_network_rule")          # NET-a: S2a-1's rule in the sandbox, its switch off
@pytest.mark.parametrize("command,shown", [("ls", {}), ("curl https://example.test/b", {"network": True})],
                         ids=["offline", "a network card"])
async def test_a_command_after_outside_content_runs_offline(command, shown, monkeypatch, turn_db):
    turn = Turn()
    replies = [call("web_extract", {"url": "https://example.test/a"}, "c1"), call("run_command", {"command": command}, "c2"),
               Reply("Done.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=table("web_extract", "run_command"),
                   confirm_command=card(turn, "command"))
    assert turn.cards == [("command", [command, []], shown)]
    assert [(tool, around["offline"]) for tool, _args, around in turn.ran] == [("web_extract", False), ("run_command", True)]


@pytest.mark.parametrize("command", ["ls", "curl https://example.test/b"], ids=["no network", "network by its text"])
async def test_after_outside_content_a_command_in_the_sandbox_reaches_its_call_online(command, monkeypatch, turn_db):
    """NET-a, its switch on (the default): the proxy judges each site the command reaches, so the gate leaves it online
    and its card says nothing of the network."""
    turn = Turn()
    replies = [call("web_extract", {"url": "https://example.test/a"}, "c1"), call("run_command", {"command": command}, "c2"),
               Reply("Done.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=table("web_extract", "run_command"),
                   confirm_command=card(turn, "command"))
    assert turn.cards == [("command", [command, []], {})]
    assert [(tool, around["offline"]) for tool, _args, around in turn.ran] == [("web_extract", False), ("run_command", False)]


async def test_a_delete_outside_the_sandbox_goes_to_the_trash(monkeypatch, turn_db):
    turn = Turn()
    command = {"command": "rm -r /tmp/turn-old", "outside_sandbox": True, "why": "it is outside"}
    await run_turn(turn, monkeypatch, turn_db, [call("run_command", command), Reply("Done.")], **_command(turn))
    assert turn.cards == [("command", ["rm -r /tmp/turn-old", []],
                           {"delete": "trash", "sandbox": "outside", "why": "it is outside"})]
    assert turn.ran[0][2] == {**CLEAR, "outside": True, "trash": True}


# A tool's own limit, on a clock that doesn't move, with 100 seconds of the turn left.
@pytest.mark.parametrize("replies,tools,own_limit,limits", [
    ([call("run_command", {"command": "ls"})], "run_command", {"run_command": 600}, [90.0]),
    ([call("run_command", {"command": "ls"})], "run_command", {"run_command": 15}, [15.0]),
    ([call("web_search", {"query": "a"}, "c1"), call("read_file", {"path": "a.md"}, "c2")], "web_search read_file",
     {"web_search": 300, "read_file": 5}, [300.0, 20.0]),
], ids=["a command leaves its reserve", "a command's own limit under the default",
        "a tool's own limit over and under the default"])
async def test_a_calls_time_limit(replies, tools, own_limit, limits, monkeypatch, turn_db):
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [*replies, Reply("Done.")], tools=table(*tools.split()),
                   own_limit=own_limit, confirm_command=card(turn, "command"))
    assert turn.limits == limits
    assert turn.tools_ran == [tool for reply in replies for tool in [reply.calls[0]["function"]["name"]]]
