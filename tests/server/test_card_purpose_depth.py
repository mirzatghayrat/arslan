"""A card's plain purpose reads a line inside another (a `$(…)`, a shell's `-c`, `eval`, `watch`, find's `-exec`) only
so deep (`card_purpose.READ_DEPTH`) and only so much (`READ_WORK` times the line's length). Past either it reads the
line as one it cannot read ("Run <program>"), and every card path still gets its title. Up to them, the reading is the
one it always was. These lines are only read here, never run."""
import time
from types import SimpleNamespace

import pytest

from server.orchestrator import tool_loop, untrusted
from server.services import approvals, card_purpose, command_confirm, command_sandbox, permissions

READ_DEPTH = card_purpose.READ_DEPTH
READ_WORK = card_purpose.READ_WORK

#: Each shape: the line whose innermost step is read `depth` lines deep, its reading there, and its program.
SHAPES = {
    "eval": (lambda depth: "eval " * depth + "rm x", "Delete 1 file or folder", "eval"),
    "watch": (lambda depth: "watch " * depth + "rm x", "Delete 1 file or folder", "watch"),
    "find -exec": (lambda depth: "find . -exec " + "eval " * (depth - 1) + "rm x", "Delete what it finds in .", "find"),
    "$( ) in eval": (lambda depth: "eval " * (depth - depth // 2) + "$(" * (depth // 2) + "rm x" + ")" * (depth // 2),
                     f"Delete 1 file or folder (and {READ_DEPTH // 2} more steps)", "eval"),
}
#: Far past the bound: deeper than Python's own frames go, read one per level.
FAR = READ_DEPTH * 16


def _unreadable(program: str) -> dict:
    """The reading of a line that cannot be read (a quote never closed): "Run <program>"."""
    return card_purpose.summarize(program + " '")


@pytest.mark.parametrize("shape", SHAPES)
def test_a_line_read_as_deep_as_the_bound_keeps_its_reading(shape):
    line, reading, _ = SHAPES[shape]
    assert card_purpose.phrase(line(READ_DEPTH), lang="en") == reading


@pytest.mark.parametrize("depth", [READ_DEPTH + 1, READ_DEPTH * 2, FAR])
@pytest.mark.parametrize("shape", SHAPES)
def test_a_line_read_past_the_bound_reads_as_one_it_cannot_read(shape, depth):
    line, _, program = SHAPES[shape]
    assert card_purpose.summarize(line(depth)) == _unreadable(program)
    assert card_purpose.phrase(line(depth), lang="en") == f"Run {program}"


@pytest.mark.parametrize("shape", SHAPES)
def test_the_bound_leaves_room_for_the_stack_a_turn_has_used(shape):
    """A turn's dispatch is already some frames deep when its card is titled."""
    line, reading, _ = SHAPES[shape]

    def deep(frames: int):
        return deep(frames - 1) if frames else card_purpose.phrase(line(READ_DEPTH), lang="en")
    assert deep(200) == reading


def _actions(count: int, tail: int, pad: int) -> tuple[str, int]:
    """`find . -exec rm -exec rm … <tail>`, then a step that is never read (`: <pad>`). Each `-exec` reads the rest
    of the step again; returns the line and how much those readings take together."""
    args = [".", *["-exec", "rm"] * count, "b" * tail]
    reread = sum(len(" ".join(args[i + 1:])) for i, a in enumerate(args) if a == "-exec")
    return " ".join(["find", *args]) + "; : " + "p" * pad, reread


def _over_the_budget(over: int) -> str:
    """A line whose readings take READ_WORK times its length, and `over` more."""
    for count in range(READ_WORK * 2, READ_WORK * 8):
        for tail in range(1, READ_WORK + 1):
            bare, reread = _actions(count, tail, 0)
            pad, rest = divmod(reread - over, READ_WORK)
            if rest == 0 and pad - len(bare) >= 0:
                line, reread = _actions(count, tail, pad - len(bare))
                assert reread == READ_WORK * len(line) + over
                return line
    raise AssertionError(f"no line takes the budget and {over} more")


def test_a_line_whose_readings_take_exactly_the_budget_keeps_its_reading():
    assert card_purpose.phrase(_over_the_budget(0), lang="en") == "Delete what it finds in ."


@pytest.mark.parametrize("over", [1, READ_WORK])
def test_a_line_whose_readings_take_more_than_the_budget_reads_as_one_it_cannot_read(over):
    assert card_purpose.summarize(_over_the_budget(over)) == _unreadable("find")


@pytest.mark.timeout(60)
@pytest.mark.parametrize("depth", [READ_DEPTH // 4, READ_DEPTH // 2, READ_DEPTH, FAR // 2])
def test_finds_inside_finds_are_read_in_bounded_time(depth):
    """Each `-exec` reads the rest of its line, and each `-exec` in that reads it again; READ_WORK bounds it all."""
    line = "find . -exec " * depth + "rm x"
    start = time.process_time()
    assert card_purpose.summarize(line) == _unreadable("find")
    assert time.process_time() - start < 5


# ── Every card path gets its title ──

DEEP = {"eval": "eval " * FAR + "rm x", "find -exec": "find . -exec " * (FAR // 2) + "rm x"}
TITLE = {"eval": "Run eval", "find -exec": "Run find"}


class _Asker:
    def __init__(self):
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": False, "scope": "once", "note": "", "by": "mac", "call_id": frame["call_id"]}


@pytest.mark.parametrize("where, lead", [({}, ""), ({"sandbox": "outside", "why": "Check"}, "Outside the sandbox · "),
                                         ({"remote_host": "me@box", "fingerprints": ["SHA256:x"]}, "On me@box · ")],
                         ids=["ordinary", "outside", "remote"])
@pytest.mark.parametrize("shape", DEEP)
async def test_the_command_card_is_shown_with_its_title(execution_db, shape, where, lead):
    asker = _Asker()
    with permissions.asking_with(asker):
        allowed = await command_confirm.Confirmations("c1").command(DEEP[shape], [], **where)
    assert allowed is False and len(asker.frames) == 1
    assert asker.frames[0]["title"].startswith(lead + TITLE[shape])


@pytest.mark.parametrize("shape", DEEP)
def test_the_card_listed_when_nobody_can_be_asked_has_its_title(shape):
    request = approvals._command_request(DEEP[shape], [], None, ask_all=True, lang="en")
    assert request.title == TITLE[shape]


@pytest.mark.parametrize("shape", DEEP)
async def test_the_network_card_after_outside_content_is_shown(execution_db, monkeypatch, shape):
    seen = []

    async def decide(request, context):
        seen.append(request)
        return SimpleNamespace(allowed=False, model_text="no")
    monkeypatch.setattr(untrusted, "external_seen", lambda: True)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(permissions, "current_asker", lambda: object())
    monkeypatch.setattr(permissions, "decide", decide)
    out = await tool_loop._network_after_outside_content(DEEP[shape], {"network": True}, sandbox_on=True,
                                                         run_outside=False, unwrapped=False, conversation_id="c1")
    assert out == {"refused": "no"}
    assert seen[0].title == "Uses the network · " + TITLE[shape]


@pytest.mark.parametrize("shape", DEEP)
async def test_a_remote_command_with_nobody_to_ask_is_refused_with_its_card_listed(execution_db, monkeypatch, shape):
    listed = []

    async def unattended(message, request, conversation_id):
        listed.append(request.title)
        return message
    monkeypatch.setattr(tool_loop, "_unattended", unattended)

    async def _resolve():
        return [{"key": "ssh_run", "description": "run"}]
    result = await tool_loop._dispatch_tool("ssh_run", {"host": "box", "command": DEEP[shape]}, "{}",
                                            resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5,
                                            tool_trace=[], convo=[], confirm_command=None, conversation_id="c1")
    assert listed == ["On box · " + TITLE[shape]]
    assert "confirmation" in str(result)
