"""One scripted turn through `run_native`, with the real gates and an isolated database, for tests that assert what a
turn does: the frames in order, the requests and what they carried, the executors and what was set around them, the
cards, each call's time limit, and what the turn returned.

The model is scripted (`Reply`), the tool table is the test's own (`table`), and every executor answers from `ANSWERS`.
A test module imports the two database fixtures, `booted_db_fixture` and `turn_db_fixture`, and its tests take
`turn_db`: a fresh copy of a database booted once per module.
"""
import asyncio
import copy
import shutil
import types
from dataclasses import dataclass, field

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from arslan import execution_budget as eb
from arslan import execution_checkpoint
from arslan.execution_budget import Budget
from server.db import session as db_session
from server.db.models import Setting
from server.orchestrator import agent_status, answer_salvage, memory, model_call, model_step, on_demand, tool_caller
from server.orchestrator import tool_execute, tool_gates, tool_loop, turn_model
from server.registry import executors
from server.services import (
    command_sandbox,
    delete_to_trash,
    desktop_status,
    lessons,
    ocr_fallback,
    permissions,
    recap_service,
    runtime_messages,
    skill_forge,
    steering,
    task_service,
    task_validation,
    terminal_exec,
)
from tests.server.conftest import boot_schema
from tests.server.test_trajectory_golden import _pin_workspace, _tc

LONG = "This is a long answer that goes out while it is written. " * 8
STOPPED_EARLY = "I didn't finish this one in a single round."
SKILL = {"key": "weekly", "name": "Weekly", "description": "d", "body": "## Trigger\nx"}


@dataclass
class Reply:
    content: str | None = None
    calls: list = field(default_factory=list)
    finish: str = "stop"
    continuation: dict | None = None
    raises: Exception | None = None          # raised after `content` went out through on_text


def refusal(status, text):
    request = httpx.Request("POST", "https://model.test/v1")
    return httpx.HTTPStatusError(text, request=request, response=httpx.Response(status, text=text, request=request))


def call(name, args, cid="c1"):
    return Reply(None, [_tc(name, args, cid)])


def batch(*calls):
    return Reply(None, [_tc(name, args, cid) for name, args, cid in calls])


def table(*keys):
    return [{"key": key, "description": f"The {key} tool."} for key in keys]


def wrap_up_at_one():
    """A budget whose soft limit is reached by the first call: from then on the turn wraps up."""
    return Budget(eb.Limits(tool_calls=40), soft=eb.Limits(tool_calls=1))


def searches(count):
    return [call("web_search", {"query": f"q{index}"}, f"s{index}") for index in range(count)]


def extract(args, *, size=0):
    from arslan.companion.research import receipt
    text = f"Body of {args['url']}, with figures 12 and 34." + "x" * size
    source = receipt(args["url"], text, truncated=False).model_dump(mode="json")
    return {"ok": True, "url": args["url"], "text": text, "source": source}


def _searched(args):
    return {"ok": True, "summary": "1 result", "results": [{"title": f"found {args.get('query')}",
                                                            "url": "https://example.test/a"}]}


def _wrote(args):
    return {"ok": True, "path": args["path"], "bytes": len(args.get("content") or "")}


ANSWERS = {"web_search": _searched, "web_extract": extract, "write_file": _wrote, "edit_file": _wrote,
           "read_file": {"ok": True, "path": "notes.md", "text": "a local note"},
           "list_dir": {"ok": True, "entries": ["a.md"]},
           "run_command": {"ok": True, "exit_code": 0, "stdout": "done"},
           "schedule_task": {"ok": True}, "attach_file": {"ok": True, "path": "a.md"},
           "start_background_work": {"ok": True},
           "desktop_look": {"ok": True, "text": "a window", "image_label": "the window",
                            "images": [{"mime_type": "image/png", "data": "cGl4ZWxz"}]}}
RESEARCH = table("web_search", "web_extract", "read_file", "list_dir", "write_file", "edit_file")
FINDERS = [*table("web_search"), on_demand.FIND_TOOLS, on_demand.USE_TOOL]
REACHABLE = [*FINDERS, *table("attach_file")]
NOTHING_FOUND = {"web_search": {"ok": True, "results": []}}


class _Model:
    def __init__(self, turn, replies):
        self.turn, self.replies = turn, list(replies)

    def native_trajectory(self):
        return True

    async def _next(self, on_text=None):
        if self.turn.before_reply:
            self.turn.before_reply.pop(0)()
        reply = self.replies.pop(0)
        if on_text is not None and reply.content:
            for start in range(0, len(reply.content), 40):
                on_text(reply.content[start:start + 40])
        if reply.raises is not None:
            raise reply.raises
        return types.SimpleNamespace(content=reply.content, tool_calls=reply.calls, finish_reason=reply.finish,
                                     continuation=reply.continuation, provider_content=None)

    async def chat_trajectory(self, system, messages, tools=None, tool_choice=None, **kwargs):
        self.turn.requests.append({"system": system, "messages": copy.deepcopy(messages), "tool_choice": tool_choice,
                                   "tools": None if tools is None else [t["function"]["name"] for t in tools]})
        self.turn.log.append("request")
        return await self._next(kwargs.get("on_text"))

    async def chat(self, system, user, history=None, tools=None, **kwargs):
        self.turn.legacy.append({"system": system, "user": user})
        self.turn.log.append("legacy request")
        return await self._next()


@dataclass
class Turn:
    """What one turn did. `log` is the order of everything, as kinds: "request", "frame:<type>", "ran:<tool>"…"""
    log: list = field(default_factory=list)
    frames: list = field(default_factory=list)
    requests: list = field(default_factory=list)
    legacy: list = field(default_factory=list)
    ran: list = field(default_factory=list)          # (tool, args, what was set around the call)
    cards: list = field(default_factory=list)        # (card, shown, keywords)
    limits: list = field(default_factory=list)
    chunks: list = field(default_factory=list)
    stored: list = field(default_factory=list)
    checkpoints: list = field(default_factory=list)
    before_reply: list = field(default_factory=list)   # called before the next reply, one each
    hooks: dict = field(default_factory=dict)          # tool -> called each time its executor runs
    returned: dict | None = None

    def kinds(self, *types_):
        return [frame["type"] for frame in self.frames if not types_ or frame["type"] in types_]

    def results(self, tool=None):
        return [frame for frame in self.frames if frame["type"] == "tool_result" and tool in (None, frame["tool"])]

    @property
    def tools_ran(self):
        return [tool for tool, _args, _around in self.ran]

    @property
    def shown(self):
        return "".join(self.chunks)

    def added(self, index):
        """The messages request `index` carries that the request before it didn't, as one text."""
        before = len(self.requests[index - 1]["messages"]) if index > 0 else 0
        return "\n".join(str(message.get("content")) for message in self.requests[index]["messages"][before:])


def _around(turn, key, answer, timeout_s=None):
    class Ran:
        async def execute(self, args):
            caller = tool_caller.current_caller()
            around = {"offline": terminal_exec.OFFLINE.get(), "outside": terminal_exec.OUTSIDE_SANDBOX.get(),
                      "unwrapped": terminal_exec.UNWRAPPED.get(), "trash": bool(delete_to_trash.TRASH.get()),
                      "caller": caller.actor if caller else None, "model": type(turn_model.current()).__name__}
            turn.ran.append((key, copy.deepcopy(args), around))
            turn.log.append(f"ran:{key}")
            for hook in turn.hooks.get(key, []):
                hook()
            return answer(args) if callable(answer) else copy.deepcopy(answer)
    ran = Ran()
    ran.key = key
    if timeout_s is not None:       # the executor declares its own limit, as a slow tool does
        ran.timeout_s = timeout_s
    return ran


def card(turn, name, answer=True, clicked=False):
    async def confirm(*shown, **own):
        if clicked:
            permissions.LAST_DECISION.set(types.SimpleNamespace(by="user"))
        turn.cards.append((name, list(shown), own))
        turn.log.append(f"card:{name}")
        return answer
    return confirm


def skill_saves(monkeypatch, saved):
    async def propose(args, **_own):
        saved["done"] = True
        return {"ok": True, "saved": args["key"], "refresh": True}
    monkeypatch.setattr(skill_forge, "propose", propose)


def message_arrives(turn, monkeypatch, conversation_id="steered"):
    """Returns a function that puts a user message in the turn's box, as one sent from the window mid-turn."""
    async def stored(_conversation, _role, content, **_own):
        turn.stored.append(content)
        return 7
    monkeypatch.setattr(memory, "add_message", stored)
    steering.open_box(conversation_id)

    async def tell(_frame):
        return None
    return lambda: steering.put(conversation_id, steering.Steer("also this", None, {"type": "user_message"}, tell,
                                                                asyncio.Queue()))


def long_turn(turn, monkeypatch, slow_tool):
    """A clock that moves 20 minutes each time `slow_tool` runs."""
    clock = types.SimpleNamespace(now=1000.0)
    monkeypatch.setattr(eb, "time", types.SimpleNamespace(monotonic=lambda: clock.now))

    def later():
        clock.now += 20 * 60
    turn.hooks.setdefault(slow_tool, []).append(later)


class _Progress:
    def __init__(self, validation_repairs=(), loop_fingerprints=()):
        self.validation_repairs, self.loop_fingerprints = validation_repairs, loop_fingerprints

    def model_copy(self, update):
        return _Progress(**{**vars(self), **update})


def _runtime(turn, acceptance):
    """A job's runtime, as the loop reads it. Its checkpoints record the loop's fingerprints."""
    runtime = types.SimpleNamespace(spec=types.SimpleNamespace(acceptance=acceptance, locale="en"),
                                    progress=_Progress(), pause_reason=None, limit_reason=None, closed=False,
                                    task_id="t1")

    async def checkpoint(reason):
        turn.checkpoints.append((reason, list(runtime.progress.loop_fingerprints)))

    async def execute_tool(_key, args, execute):
        return await execute(args)
    runtime.checkpoint, runtime.execute_tool = checkpoint, execute_tool
    return runtime


def job(turn, monkeypatch, reports, *, answer_only=False, links=()):
    """The turn runs as a job with one acceptance check, which gives `reports` in order."""
    reports = list(reports)
    check = types.SimpleNamespace(evaluator="auto", model_dump=lambda **_own: {"kind": "mentions", "target": "x"})
    runtime = _runtime(turn, [check])
    monkeypatch.setattr(task_service, "current", lambda: runtime)
    monkeypatch.setattr(task_service, "answer_only", lambda: answer_only)

    async def validate(_runtime, _output, _trace, **_own):
        return {"failures": reports.pop(0)}
    monkeypatch.setattr(task_validation, "validate_output", validate)
    monkeypatch.setattr(task_validation, "failures", lambda report: report["failures"])
    monkeypatch.setattr(task_validation, "unverified_links", lambda _answer, *_args: list(links))
    monkeypatch.setattr(task_validation, "failure_output",
                        lambda output, report, _locale: f"{output}\n[checks failed: {report['failures']}]")
    return runtime


def lane(turn):
    """A progress lane (`run_native(progress_lane=…)`), with no checks."""
    return _runtime(turn, [])


async def run_turn(turn, monkeypatch, database, replies, *, tools=None, later_tools=None, saved=None, answers=None,
                   own_limit=None, budget=None, ocr=False, history=(), **kwargs):
    """Runs one turn. `later_tools` is the table once `saved["done"]` is set (a card that saved something)."""
    _pin_workspace(monkeypatch)
    model_step._BAD_TOOLS.clear()        # per process: a refusal in one turn must not reach the next
    model_step._REFUSES_IMAGES.clear()
    on_demand._used.clear()

    async def english():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", english)
    monkeypatch.setattr(lessons, "later", lambda coroutine: coroutine.close())
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(desktop_status, "note_step", lambda *_args: None)
    monkeypatch.setattr(desktop_status, "note_plan", lambda *_args: None)
    monkeypatch.setattr(agent_status, "recent_files", lambda *_args, **_own: [])
    within = tool_execute.within

    async def limited(awaitable, timeout, **own):
        turn.limits.append(timeout)
        return await within(awaitable, timeout, **own)
    monkeypatch.setattr(tool_execute, "within", limited)
    monkeypatch.setattr(answer_salvage, "within", limited)

    async def waited(_seconds):
        return None
    monkeypatch.setattr(model_call, "sleep", waited)
    monkeypatch.setattr(execution_checkpoint, "save", waited)

    async def event(*_args):
        return None
    monkeypatch.setattr(recap_service, "log_event", event)
    if ocr:
        monkeypatch.setattr(ocr_fallback, "read_locally", lambda *_args, **_own: ("text on the window", "ok"))
    own_limit = own_limit or {}
    if own_limit:
        monkeypatch.setattr(eb, "time", types.SimpleNamespace(monotonic=lambda: 1000.0))
        budget = Budget(eb.Limits(wall_seconds=100))
    for key, answer in {**ANSWERS, **(answers or {})}.items():
        monkeypatch.setitem(executors.EXECUTORS, key, _around(turn, key, answer, own_limit.get(key)))
    async with database() as db:
        db.add(Setting(key="default_permission_mode", value="ask"))      # a card for every command
        await db.commit()
    tools = RESEARCH if tools is None else tools
    saved = saved if saved is not None else {"done": False}

    async def resolve():
        return copy.deepcopy(later_tools if later_tools and saved["done"] else tools)

    def emitted(frame):
        turn.frames.append(copy.deepcopy(frame))
        turn.log.append(f"frame:{frame.get('type')}")
    kwargs.setdefault("allow_escalation", False)
    with eb.scope(budget or Budget()):
        turn.returned = await tool_loop.run_native(
            system="SYS", user_content="the request", history=list(history), emit=emitted, on_chunk=turn.chunks.append,
            resolve_tools=resolve, adapter_override=_Model(turn, replies), **kwargs)
    return turn


def writes_need_a_card(monkeypatch):
    """Writing in Arslan's own folder takes no card; this turn's folder is not its own."""
    async def no():
        return False
    monkeypatch.setattr(tool_gates, "_writing_in_own_folder", no)


@pytest.fixture(scope="module", name="booted_db")
def booted_db_fixture(tmp_path_factory):
    """One booted database to copy: the migrations take seconds, and a turn needs only a fresh file."""
    path = tmp_path_factory.mktemp("turns") / "booted.db"

    async def boot():
        engine = db_session.build_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as connection:
            await connection.run_sync(boot_schema)
        await engine.dispose()
    asyncio.run(boot())
    return path


@pytest.fixture(name="turn_db")
async def turn_db_fixture(monkeypatch, tmp_path, booted_db):
    path = tmp_path / "turn.db"
    shutil.copy(booted_db, path)
    engine = db_session.build_engine(f"sqlite+aiosqlite:///{path}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    yield maker
    await engine.dispose()
