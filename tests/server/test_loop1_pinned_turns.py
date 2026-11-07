"""LOOP1 L0: what a turn does today, pinned byte for byte, so the restructure can prove it changed nothing.

Each scenario scripts a model and runs one turn through `run_native` with the real gates and an isolated database.
The log holds, in order, every frame and chunk the turn emitted, every request it made (messages, tool names,
tool_choice), every executor it ran, and what it returned or raised. The tool table is this file's own, so a change to
a real tool's description doesn't touch these files. `expect` says what the scenario must reach, so a pin can't quietly
hold a script that went wrong.

Temporary: DELETE-BY: v0.1.64, with LOOP1's slice z (docs/plans/0164/LOOP1-agent-loop.md).

If your PR changes what a turn does on purpose, run the command below and commit the JSON, so the review reads the diff:
ARSLAN_UPDATE_GOLDEN=1 pytest tests/server/test_loop1_pinned_turns.py
"""
import asyncio
import base64
import copy
import hashlib
import json
import os
import shutil
import types
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from arslan import execution_budget as eb
from arslan import execution_checkpoint
from arslan.execution_budget import Budget, Limits
from server.db import session as db_session
from server.db.models import Setting
from server.orchestrator import (
    agent_status,
    answer_salvage,
    memory,
    model_call,
    on_demand,
    tool_caller,
    tool_loop,
    turn_model,
)
from server.orchestrator.untrusted import GUARD_NOTE
from server.registry import executors
from server.services import (
    background_jobs,
    capability_flow,
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
    tool_intent,
)
from tests.server import test_trajectory_golden as golden
from tests.server.conftest import boot_schema

GOLDEN = Path(__file__).parent / "golden" / "loop1"
REGENERATE = "ARSLAN_UPDATE_GOLDEN=1 pytest tests/server/test_loop1_pinned_turns.py"
LONG = "This is a long answer that goes out while it is written. " * 8
PIXELS = base64.b64encode(b"pixels").decode()


@dataclass
class Reply:
    content: str | None = None
    calls: list = field(default_factory=list)
    finish: str = "stop"
    continuation: dict | None = None
    provider_content: dict | None = None
    raises: Exception | None = None          # raised after `content` went out through on_text


def _refusal(status, text):
    request = httpx.Request("POST", "https://model.test/v1")
    return httpx.HTTPStatusError(text, request=request, response=httpx.Response(status, text=text, request=request))


class _Model:
    """The model of one scenario. The loop reads `_provider` for what it may do, so each scenario says."""

    def __init__(self, log, replies, provider, expected):
        self.log, self.replies, self._provider, self.expected = log, list(replies), provider, expected

    def native_trajectory(self):
        return True

    async def _next(self, on_text=None):
        reply = self.replies.pop(0)
        if on_text is not None and reply.content:
            for start in range(0, len(reply.content), 40):
                on_text(reply.content[start:start + 40])
        if reply.raises is not None:
            raise reply.raises
        return types.SimpleNamespace(content=reply.content, tool_calls=reply.calls, finish_reason=reply.finish,
                                     continuation=reply.continuation, provider_content=reply.provider_content)

    async def _names(self, tools):
        """The names are pinned. The schemas are compared with what the table gives now, in order, so another lane's
        edit to a description or a parameter changes no pin, and a request that sends anything else fails."""
        if tools is None:
            return None
        names = [t["function"]["name"] for t in tools]
        assert tools == [s for s in await self.expected() if s["function"]["name"] in names], (
            f"a request sent schemas its table doesn't give: {names}")
        return names

    async def chat_trajectory(self, system, messages, tools=None, tool_choice=None, **kwargs):
        self.log.append(["request", {"system": system.replace(GUARD_NOTE, "<GUARD_NOTE>"),
                                     "messages": copy.deepcopy(messages), "tool_choice": tool_choice,
                                     "tools": await self._names(tools), "max_tokens": kwargs.get("max_tokens")}])
        return await self._next(kwargs.get("on_text"))

    async def chat(self, system, user, history=None, tools=None, **kwargs):
        self.log.append(["legacy request", {"system": system.replace(GUARD_NOTE, "<GUARD_NOTE>"), "user": user,
                                            "history": copy.deepcopy(history), "tools": await self._names(tools),
                                            "max_tokens": kwargs.get("max_tokens")}])
        return await self._next()

    async def chat_stream(self, system, user, history=None):
        self.log.append(["stream request", {"system": system.replace(GUARD_NOTE, "<GUARD_NOTE>"), "user": user,
                                            "history": copy.deepcopy(history)}])
        for piece in ("plain ", "streamed ", "answer"):
            yield piece


def _around_the_call():
    """What the loop set around the executor: what the call may reach, who is calling, on which model."""
    caller = tool_caller.current_caller()
    return {"offline": terminal_exec.OFFLINE.get(), "outside": terminal_exec.OUTSIDE_SANDBOX.get(),
            "unwrapped": terminal_exec.UNWRAPPED.get(), "caller": caller.actor if caller else None,
            "model": type(turn_model.current()).__name__,
            **({"trash": True} if delete_to_trash.TRASH.get() else {})}     # only when set: other pins stay as they are


class _Ran:
    """An executor that records its call and answers from the scenario."""

    def __init__(self, log, key, answer, timeout_s=None):
        self.log, self.key, self.answer = log, key, answer
        if timeout_s is not None:       # the executor declares its own limit, as a slow tool does
            self.timeout_s = timeout_s

    async def execute(self, args):
        self.log.append(["ran", self.key, copy.deepcopy(args), _around_the_call()])
        return self.answer(args) if callable(self.answer) else copy.deepcopy(self.answer)


class _Progress:
    def __init__(self, validation_repairs=(), loop_fingerprints=()):
        self.validation_repairs, self.loop_fingerprints = validation_repairs, loop_fingerprints

    def model_copy(self, update):
        return _Progress(**{**vars(self), **update})


def _table(*keys):
    return [{"key": key, "description": f"The {key} tool."} for key in keys]


def _mcp(*keys):
    return [{"key": key, "description": f"The server's {key}.", "input_schema": {"type": "object"}} for key in keys]


def _searched(args):
    return {"ok": True, "summary": "1 result", "results": [{"title": f"found {args.get('query')}",
                                                            "url": "https://example.test/a"}]}


def _extract(args, *, size=0):
    from arslan.companion.research import receipt
    text = f"Body of {args['url']}, with figures 12 and 34." + "x" * size
    source = receipt(args["url"], text, truncated=False).model_dump(mode="json")
    source["retrieved_at"] = "2026-10-01T00:00:00+00:00"
    return {"ok": True, "url": args["url"], "text": text, "source": source}


def _wrote(args):
    return {"ok": True, "path": args["path"], "bytes": len(args.get("content") or "")}


ANSWERS = {"web_search": _searched, "web_extract": _extract, "write_file": _wrote, "edit_file": _wrote,
           "read_file": {"ok": True, "path": "notes.md", "text": "a local note"},
           "list_dir": {"ok": True, "entries": ["a.md"]},
           "run_command": {"ok": True, "exit_code": 0, "stdout": "done"},
           "schedule_task": {"ok": True},
           "attach_file": {"ok": True, "path": "a.md"},
           "read_skill": {"ok": True, "text": "the method"},
           "start_background_work": {"ok": True},
           "desktop_look": {"ok": True, "text": "a window", "image_label": "the window",
                            "images": [{"mime_type": "image/png", "data": PIXELS}]},
           "mcp_1__lookup": {"ok": True, "summary": "looked up"}, "mcp_2__other": {"ok": True, "summary": "other"}}
RESEARCH = _table("web_search", "web_extract", "read_file", "list_dir", "write_file", "edit_file")
FINDERS = [*_table("web_search"), on_demand.FIND_TOOLS, on_demand.USE_TOOL]
REACHABLE = [*FINDERS, *_table("attach_file")]
NOTHING_FOUND = {"web_search": {"ok": True, "results": []}}
LINKS = "| a | https://example.test/a |\n| b | https://example.test/b |\n| c | https://not-read.test/z |"
THOUGHT = {"protocol": "openai", "reasoning": "thinking it over"}
UPDATE = {"protocol": "anthropic", "updates": True, "content": [{"type": "thinking", "thinking": "Checking the file."}]}


def _stopped_by_the_sandbox(_args):
    if terminal_exec.OUTSIDE_SANDBOX.get():
        return {"ok": True, "exit_code": 0, "stdout": "done"}
    return {"ok": False, "sandbox_denied": True, "error": "the sandbox stopped it"}


def _call(name, args, cid="c1"):
    return Reply(None, [golden._tc(name, args, cid)])


def _batch(*calls):
    return Reply(None, [golden._tc(name, args, cid) for name, args, cid in calls])


def _searches(count):
    return [_call("web_search", {"query": f"q{index}"}, f"s{index}") for index in range(count)]


def _looks(count):
    return [_call("desktop_look", {"app": f"app {index}"}, f"l{index}") for index in range(count)]


def _repeated(name, args):
    """A model that keeps sending one refused call, far past where the no-progress stop should end it."""
    return [*[_call(name, args, f"c{index}") for index in range(8)], Reply("Stopped asking.")]


def _repeated_bad_json():
    return [*[Reply(None, [{"id": f"c{index}", "function": {"name": "web_search", "arguments": '{"query": '},
                            "arguments_raw": '{"query": '}]) for index in range(8)], Reply("Stopped asking.")]


# Each scenario: `replies`, `expect`, then what run_native gets (`tools`, `history`, its keywords), `answers`, `budget`,
# `provider`, `streams` (False: the "show answers when complete" setting), `job` (acceptance checks: the reports they
# give), `setup` (for the few that need something else in place).
SCENARIOS: dict[str, dict] = {
    # ── answers, no tools ──
    "answer_short": dict(replies=[Reply("Hello there.")], expect="Hello there."),
    "answer_long_streamed": dict(replies=[Reply(LONG)], expect='"chunk"'),
    "answer_not_streamed": dict(replies=[Reply(LONG)], streams=False, expect='"chunk"'),
    "answer_empty_salvaged": dict(replies=[Reply(""), Reply("A plain answer from the salvage.")], expect="legacy request"),
    "answer_empty_nothing_usable": dict(replies=[Reply(""), Reply('{"tool": "web_search"}')], expect="say it another way"),
    "plain_stream": dict(replies=[], tools=[], stream_without_tools=True, expect="stream request"),
    "plain_stream_checked": dict(replies=[], tools=[], stream_without_tools=True, job=[["bad"]], expect="checks failed"),
    "deferral_bounced": dict(replies=[Reply("I'll fetch that for you now."), Reply("Here is the honest answer.")],
                             expect="only promises future action"),
    "claim_bounced": dict(replies=[Reply("I searched and found it."), Reply("I did not; here is what I know.")],
                          expect="lacks a successful web_search receipt"),
    "claim_bounced_until_salvaged": dict(replies=[
        Reply("I searched and found it."), Reply("I searched again."), Reply("I searched a third time."),
        Reply("An honest answer from what I know.")], expect="legacy request"),
    "claim_replaced_from_findings": dict(replies=[
        _call("read_file", {"path": "a.md"}), Reply("I searched and found it."), Reply("I searched again."),
        Reply("I searched a third time."), Reply("Written from the notes.")], expect="Reference notes"),
    "claim_with_findings_nothing_usable": dict(replies=[
        _call("read_file", {"path": "a.md"}), Reply("I searched and found it."), Reply("I searched again."),
        Reply("I searched a third time."), Reply("I searched once more.")], expect="didn't finish"),
    "salvage_still_claims": dict(replies=[
        Reply("I searched and found it."), Reply("I searched again."), Reply("I searched a third time."),
        Reply("I searched one more time.")], expect="say it another way"),
    "protocol_text_bounced": dict(replies=[Reply('Let me look {"tool": "web_search", "args": {"query": "x"}}'),
                                           Reply("A plain answer.")], expect="Non-executable tool-call text omitted"),
    "protocol_text_stops_the_stream": dict(replies=[Reply(LONG + '{"tool": "web_search", "args": {"query": "x"}}'),
                                                    Reply("A plain answer after the stopped stream.")],
                                           expect="stream_restart"),
    "capability_denied_bounced": dict(replies=[Reply("I can't save that to a file.", continuation=THOUGHT),
                                               Reply("I can write it now.")], expect="Your answer says you cannot write"),
    "echo_stripped_drops_the_continuation": dict(replies=[
        Reply("<agent_status>an echo</agent_status>\nI can't save that to a file.", continuation=THOUGHT),
        Reply("I can write it now.")], expect="Your answer says you cannot write"),
    "capability_denied_twice_is_kept": dict(replies=[Reply("I can't save that to a file."),
                                                     Reply("I still can't save that to a file.")],
                                            expect="I still can't save that to a file."),
    "streamed_claim_replaced": dict(replies=[Reply("I searched everywhere. " + LONG), Reply("A corrected answer.")],
                                    expect="stream_restart"),
    "streamed_claim_kept": dict(replies=[
        Reply("I searched everywhere. " + LONG), Reply("I searched everywhere again. " + LONG),
        Reply("I searched everywhere a third time. " + LONG), Reply("")], expect="legacy request"),
    "error_after_text": dict(replies=[Reply(LONG, raises=_refusal(400, "bad request"))], expect="model_error_after_text"),
    # ── tool calls ──
    "one_call": dict(replies=[Reply("Looking it up.", [golden._tc("web_search", {"query": "lighthouse"}, "c1")]),
                              Reply("Lighthouses guide ships.")], expect="Looking it up."),
    "narration_released": dict(replies=[Reply(LONG, [golden._tc("web_search", {"query": "x"}, "c1")]),
                                        Reply("And the rest.")], expect="And the rest."),
    "progress_updates": dict(replies=[Reply(None, [golden._tc("read_file", {"path": "a.md"}, "c1")], continuation=UPDATE),
                                      Reply("Read it.")], expect="Checking the file."),
    "reads_run_together": dict(replies=[
        _batch(("web_search", {"query": "a"}, "c1"), ("read_file", {"path": "b.md"}, "c2"),
               ("list_dir", {"path": "~/c"}, "c3"), ("write_file", {"path": "d.md", "content": "x"}, "c4"),
               ("web_search", {"query": "e"}, "c5")), Reply("All done.")], expect='"tool_result"'),
    "cut_off_call": dict(replies=[Reply(None, [golden._tc("write_file", {"path": "a.md", "content": "par"}, "c1")],
                                        finish="length"), Reply("Answered instead.")], expect="output_truncated"),
    "three_cuts_force_text": dict(replies=[
        Reply(None, [golden._tc(name, {"path": "a.md"}, f"c{name}")], finish="length")
        for name in ("write_file", "edit_file", "read_file")] + [Reply("What is verified, and what remains.")],
        expect="kept exceeding the output limit"),
    "arguments_not_json": dict(replies=[
        Reply(None, [{"id": "c1", "function": {"name": "web_search", "arguments": '{"query": '},
                      "arguments_raw": '{"query": '}]), Reply("Done.")], expect="invalid_arguments_json"),
    "arguments_not_the_schema": dict(replies=[_call("write_file", {"path": "a.md"}), Reply("Done.")],
                                     expect="missing required 'content'"),
    "unknown_tool": dict(replies=[_call("no_such_tool", {"x": 1}), Reply("I can't do that.")], expect="tool_unavailable"),
    "fallback_call_ids": dict(replies=[
        Reply(None, [{"id": "", "function": {"name": "web_search", "arguments": {"query": "a"}}},
                     {"id": "dup", "function": {"name": "read_file", "arguments": {"path": "b.md"}}},
                     {"id": "dup", "function": {"name": "web_search", "arguments": {"query": "c"}}}]),
        Reply("Done.")], expect='"dup"'),
    "gemini_pairs": dict(replies=[
        Reply("narration", [golden._tc("web_search", {"query": "g"}, "gemini_0", provider_id="fc-1")],
              provider_content={"provider": "gemini", "parts": [
                  {"functionCall": {"id": "fc-1", "name": "web_search", "args": {"query": "g"}},
                   "thoughtSignature": "sig"}]}), Reply("gemini answer")], expect="thoughtSignature"),
    "update_plan": dict(replies=[
        _batch(("update_plan", {"items": [{"text": "first", "status": "in_progress"}]}, "c1"),
               ("web_search", {"query": "x"}, "c2")), Reply("Done.")],
        tools=_table("update_plan", "web_search"), expect="first"),
    "plan_change_without_project": dict(replies=[
        _call("propose_plan_change", {"levels": [{"name": "one", "band": "doing"}], "reason": "changed"}),
        Reply("No project here.")], tools=_table("propose_plan_change"), expect="this conversation has no project"),
    "skill_card_reads_the_tools_again": dict(replies=[
        _call("create_skill", {"key": "weekly", "name": "Weekly", "description": "d", "body": "## Trigger\nx"}),
        _call("read_skill", {"key": "weekly"}), Reply("Saved it.")], tools=_table("create_skill"),
        later_tools=_table("create_skill", "read_skill"), setup="skill_saved", expect="the method"),
    "capability_card_stays_the_same_table": dict(replies=[
        _call("propose_capability", {"candidate_id": "c9", "why": "an xlsx reader"}), Reply("Asked.")],
        tools=_table("propose_capability"), setup="capability_declined", expect="declined"),
    "choice_card": dict(replies=[
        Reply("Which one?", [golden._tc("ask_user_choice", {"question": "Which?", "options": [
            {"label": "A"}, {"label": "B"}]}, "c1"), golden._tc("web_search", {"query": "never run"}, "c2")])],
        tools=_table("ask_user_choice", "web_search"), expect='"clarify"'),
    "choice_card_refused": dict(replies=[_call("ask_user_choice", {"question": "Which?", "options": ["only one"]}),
                                         Reply("Plain question instead.")], tools=_table("ask_user_choice"),
                                expect="needs a question plus 2-4"),
    "choice_card_after_text": dict(replies=[
        Reply(LONG, [golden._tc("ask_user_choice", {"question": "Which?", "options": ["A", "B"]}, "c1")])],
        tools=_table("ask_user_choice"), expect='"clarify"'),
    "escalate": dict(replies=[_call("escalate", {"kind": "capability", "need": "a scanner", "context": "PDF"})],
                     allow_escalation=True, expect='"escalation"'),
    "escalate_not_allowed": dict(replies=[_call("escalate", {"need": "a scanner"}), Reply("I can't.")],
                                 expect="tool_unavailable"),
    "secret_in_arguments": dict(replies=[
        _call("web_search", {"query": "x", "password": "not-a-real-one"}),
        Reply("Done.")], expect="credentials_not_tool_data"),
    # ── on demand ──
    "find_then_use": dict(replies=[
        _call("find_tools", {"query": "attach file"}), _call("use_tool", {"name": "attach_file", "arguments": {
            "path": "a.md"}}), Reply("Attached.")], tools=FINDERS, callable=REACHABLE, expect='"attach_file"'),
    "direct_name_of_an_unshown_tool": dict(replies=[_call("attach_file", {"path": "a.md"}), Reply("Attached.")],
                                           tools=FINDERS, callable=REACHABLE, expect='"ran"'),
    "use_tool_refused": dict(replies=[
        _call("use_tool", {"name": "web_search", "arguments": {"query": "x"}}),
        _call("use_tool", {"name": "attach_file", "arguments": {}}), _call("use_tool", {"name": "nothing"}),
        Reply("Done.")], tools=FINDERS, callable=REACHABLE, expect="already in your tool list"),
    "unknown_with_finders": dict(replies=[_call("nothing_at_all", {}), Reply("Done.")], tools=FINDERS, callable=REACHABLE,
                                 expect="tool_unavailable"),
    "use_tool_names_a_command_unattended": dict(replies=[
        _call("use_tool", {"name": "run_command", "arguments": {"command": "ls"}}), Reply("I can't run it.")],
        tools=FINDERS, callable=REACHABLE, expect="Scheduled runs don't run commands"),
    # ── stops ──
    "no_progress_without_saving": dict(replies=[*_searches(5), Reply("Blocked; here is what is verified.")],
                                       tools=_table("web_search"), answers=NOTHING_FOUND,
                                       expect="Repeated actions made no progress"),
    "no_progress_then_saves": dict(replies=[
        *_searches(5), _call("web_search", {"query": "more"}, "w1"),
        _call("write_file", {"path": "report.md", "content": "# Report"}, "w2"), Reply("Saved report.md.")],
        tools=_table("web_search", "write_file"), answers=NOTHING_FOUND, expect="The deliverable is saved"),
    "no_progress_refusals_force_text": dict(replies=[
        *_searches(5), _call("web_search", {"query": "more"}, "w1"), _call("web_search", {"query": "again"}, "w2"),
        Reply("Text only now.")], tools=_table("web_search", "write_file"), answers=NOTHING_FOUND,
        expect="task_no_progress"),
    "soft_limit_wraps_up": dict(replies=[
        _call("list_dir", {"path": "~/a"}, "c1"),
        _batch(("run_command", {"command": "ls"}, "c2"), ("web_search", {"query": "b"}, "c3"),
               ("write_file", {"path": "a.md", "content": "x"}, "c4")), Reply("Wrapped up.")],
        tools=_table("list_dir", "web_search", "write_file", "run_command"),
        budget=dict(limits=Limits(tool_calls=40), soft=Limits(tool_calls=1)),
        setup="command_card", expect="Wrapping up: no more research"),
    "choice_card_while_wrapping_up": dict(replies=[
        _call("web_search", {"query": "a"}, "c1"), _call("ask_user_choice", {"question": "Which?", "options": ["A", "B"]}, "c2"),
        Reply("Wrapped up.")], tools=_table("web_search", "ask_user_choice"),
        budget=dict(limits=Limits(tool_calls=40), soft=Limits(tool_calls=1)), expect="Wrapping up: no more research"),
    "bookkeeping_while_wrapping_up": dict(replies=[
        _call("web_search", {"query": "a"}, "c1"),
        _batch(("update_plan", {"items": [{"text": "finish", "status": "in_progress"}]}, "c2"),
               ("propose_plan_change", {"levels": [{"name": "one", "band": "doing"}], "reason": "r"}, "c3"),
               ("find_tools", {"query": "attach"}, "c4"), ("web_search", {"query": "b"}, "c5")), Reply("Wrapped up.")],
        tools=[*_table("web_search", "update_plan", "propose_plan_change"), on_demand.FIND_TOOLS],
        callable=[*_table("web_search", "update_plan", "propose_plan_change", "attach_file"), on_demand.FIND_TOOLS],
        budget=dict(limits=Limits(tool_calls=40), soft=Limits(tool_calls=1)), expect="this conversation has no project"),
    "saved_before_the_stop_is_not_saved_after": dict(replies=[
        _call("write_file", {"path": "first.md", "content": "x"}, "w0"), *_searches(5),
        _call("write_file", {"path": "second.md", "content": "y"}, "w1"), Reply("Saved again.")],
        tools=_table("web_search", "write_file"), answers=NOTHING_FOUND, expect="second.md"),
    "hard_tool_limit_mid_batch": dict(replies=[
        _batch(("web_search", {"query": "a"}, "c1"), ("write_file", {"path": "x.md", "content": "y"}, "c2"),
               ("web_search", {"query": "c"}, "c3")), Reply("From what I have.")],
        budget=dict(limits=Limits(tool_calls=2)), expect="this call did not run"),
    "max_tool_calls_forces_text": dict(replies=[_call("web_search", {"query": "q"}), Reply("Final from the forced step.")],
                                       max_tool_calls=1, expect="Tool budget exhausted"),
    "forced_step_ignores_a_call": dict(replies=[
        _call("web_search", {"query": "q"}), Reply("narration", [golden._tc("web_search", {"query": "z"}, "c2")]),
        Reply("Written from the notes.")], max_tool_calls=1, expect="Reference notes"),
    "request_limit_closes_after_work": dict(replies=[_call("web_search", {"query": "a"}), _call("web_search", {"query": "b"})],
                                            budget=dict(limits=Limits(model_requests=2)),
                                            expect="task_budget_exhausted"),
    "request_limit_without_work_raises": dict(replies=[Reply("I searched for it."), Reply("I searched for it again.")],
                                              budget=dict(limits=Limits(model_requests=2)), expect='"raised"'),
    "closing_lines_after_work": dict(replies=[
        _call("write_file", {"path": "a.md", "content": "x"}, "c1"), _call("edit_file", {
            "path": "a.md", "old_string": "x", "new_string": "y"}, "c2"), _call("read_file", {"path": "a.md"}, "c3"),
        Reply("Done.")], expect="End your final reply with four short lines"),
    "research_notes_and_link_check": dict(replies=[
        _batch(("web_extract", {"url": "https://example.test/a"}, "c1"), ("web_extract", {"url": "https://example.test/b"}, "c2")),
        _call("write_file", {"path": "report.md", "content": LINKS}, "c3"), Reply("Saved report.md.")],
        expect="[Host check on report.md"),
    "oversized_batch": dict(replies=[
        _batch(*[("web_extract", {"url": f"https://example.test/{letter}"}, letter) for letter in "abc"]),
        Reply("Done.")], answers={"web_extract": lambda args: _extract(args, size=38_000)},
        expect="exceeded the bounded delivery window"),
    "big_batch_kept_whole": dict(replies=[
        _batch(*[("web_extract", {"url": f"https://example.test/{letter}"}, letter) for letter in "abc"]), Reply("Done.")],
        answers={"web_extract": lambda args: _extract(args, size=20_000)},
        history=[{"role": "user", "content": "old question " * 1800}, {"role": "assistant", "content": "old answer " * 2000}],
        expect="Earlier conversation turns were compacted"),
    "several_notes_at_once": dict(replies=[
        _call("web_extract", {"url": "https://example.test/a"}, "c1"), _call("write_file", {"path": "a.md", "content": "x"}, "c2"),
        Reply("Done.")], tools=_table("web_extract", "write_file", "start_background_work"), setup="long_turn",
        slow="write_file",
        history=[{"role": "user", "content": "old question " * 5000}, {"role": "assistant", "content": "old answer " * 5000},
                 {"role": "user", "content": "next"}, {"role": "assistant", "content": "ok"}],
        expect="End your final reply with four short lines"),
    "long_history_compacted": dict(replies=[_call("web_search", {"query": "a"}), Reply("Done.")],
                                   history=[{"role": "user", "content": "old question " * 3000},
                                            {"role": "assistant", "content": "old answer " * 3000},
                                            {"role": "user", "content": "next question"},
                                            {"role": "assistant", "content": "next answer"}],
                                   expect="Earlier conversation turns were compacted"),
    "long_turn_note": dict(replies=[_call("web_search", {"query": "a"}), Reply("Done.")],
                           tools=_table("web_search", "start_background_work"), setup="long_turn",
                           expect="This turn has been working for 10 minutes"),
    "presearch": dict(replies=[Reply("Answered after the first search.")], force_tools=True, setup="presearch",
                      expect="the pre-search"),
    "message_sent_meanwhile": dict(replies=[
        _batch(("write_file", {"path": "a.md", "content": "x"}, "c1"), ("write_file", {"path": "b.md", "content": "y"}, "c2")),
        Reply("Read your message.")], steerable=True, conversation_id="steered", setup="message_meanwhile",
        steer_on="write_file", expect="skipped_for_message"),
    "big_batch_kept_with_its_message": dict(replies=[
        _batch(*[("web_extract", {"url": f"https://example.test/{letter}"}, letter) for letter in "abc"]), Reply("Done.")],
        answers={"web_extract": lambda args: _extract(args, size=20_000)}, steerable=True, conversation_id="steered",
        setup="message_meanwhile", steer_on="web_extract",
        history=[{"role": "user", "content": "old question " * 1800}, {"role": "assistant", "content": "old answer " * 2000}],
        expect="also this"),
    "turn_notes_and_status": dict(replies=[Reply("Hello.")], turn_notes=["This turn came from the iPhone."],
                                  expect="This turn came from the iPhone."),
    # ── the batch's own gates ──
    "budget_spent_then_choice_card": dict(replies=[
        _batch(("web_search", {"query": "a"}, "c1"), ("ask_user_choice", {"question": "Which?", "options": ["A", "B"]}, "c2"))],
        tools=_table("web_search", "ask_user_choice"), budget=dict(limits=Limits(tool_calls=1)), expect='"clarify"'),
    "reads_while_wrapping_up": dict(replies=[
        _call("list_dir", {"path": "~/a"}, "c1"),
        _batch(("read_file", {"path": "b.md"}, "c2"), ("list_dir", {"path": "~/c"}, "c3"),
               ("write_file", {"path": "d.md", "content": "x"}, "c4")), Reply("Wrapped up.")],
        budget=dict(limits=Limits(tool_calls=40), soft=Limits(tool_calls=1)), expect="Wrapping up: no more research"),
    "escalate_with_bad_arguments": dict(replies=[_call("escalate", {"kind": "capability"}), Reply("Asking another way.")],
                                        tools=[{"key": "escalate", "description": "d", "input_schema": {
                                            "type": "object", "required": ["need"], "properties": {"need": {"type": "string"}}}}],
                                        allow_escalation=True, expect="missing required 'need'"),
    "presearch_counts_toward_no_progress": dict(replies=[*_searches(4), Reply("Blocked.")], tools=_table("web_search"),
                                                answers=NOTHING_FOUND, force_tools=True, setup="presearch",
                                                expect="Repeated actions made no progress"),
    "older_screenshots_trimmed": dict(replies=[*_looks(3), Reply("Seen them.")], tools=_table("desktop_look"),
                                      expect="no longer shown"),
    "screenshots_kept_when_the_provider_clears": dict(replies=[*_looks(3), Reply("Seen them.")], tools=_table("desktop_look"),
                                                      provider=dict(trims_context_server_side=lambda: True), expect="Seen them."),
    "screenshots_trimmed_once_the_provider_stops_clearing": dict(replies=[
        *_looks(3), Reply(raises=_refusal(400, "messages: invalid role tool, tool_call_id is not supported")),
        _call("list_dir", {"path": "~/a"}, "c9"), Reply("Seen them.")], tools=_table("desktop_look", "list_dir"),
        provider=dict(trims_context_server_side=lambda: True), expect="no longer shown"),
    "bad_json_repeated": dict(replies=_repeated_bad_json(), expect="task_no_progress"),
    "schema_refused_repeated": dict(replies=_repeated("write_file", {"path": "a.md"}), expect="task_no_progress"),
    "find_tools_repeated": dict(replies=_repeated("find_tools", {"query": "attach"}), tools=FINDERS, callable=REACHABLE,
                                expect="task_no_progress"),
    "use_tool_refused_repeated": dict(replies=_repeated("use_tool", {"name": "nothing"}), tools=FINDERS, callable=REACHABLE,
                                      expect="task_no_progress"),
    "bad_choice_repeated": dict(replies=_repeated("ask_user_choice", {"question": "Which?", "options": ["only"]}),
                                tools=_table("ask_user_choice"), expect="task_no_progress"),
    "message_waiting_before_the_first_call": dict(replies=[
        _batch(("write_file", {"path": "a.md", "content": "x"}, "c1"), ("write_file", {"path": "b.md", "content": "y"}, "c2")),
        Reply("Read your message.")], steerable=True, conversation_id="steered", setup="message_before_the_calls",
        expect="skipped_for_message"),
    # ── the hard stop ──
    "streamed_text_then_hard_stop": dict(replies=[Reply(LONG, [golden._tc("web_search", {"query": "a"}, "c1")]),
                                                  _call("web_search", {"query": "b"}, "c2")],
                                         budget=dict(limits=Limits(model_requests=2)), expect='"task_budget_exhausted"'),
    "job_at_the_hard_stop": dict(replies=[_call("web_search", {"query": "a"}, "c1"), _call("web_search", {"query": "b"}, "c2")],
                                 budget=dict(limits=Limits(model_requests=2)), job=[], expect='"pause_reason": "task_budget_exhausted"'),
    "job_saved_at_the_hard_stop": dict(replies=[_call("write_file", {"path": "a.md", "content": "x"}, "c1"),
                                                _call("web_search", {"query": "b"}, "c2")],
                                       budget=dict(limits=Limits(model_requests=2)), job=[],
                                       expect='"limit_reason": "task_budget_exhausted"'),
    "background_job_at_the_hard_stop": dict(replies=[_call("web_search", {"query": "a"}, "c1"), _call("web_search", {"query": "b"}, "c2")],
                                            budget=dict(limits=Limits(model_requests=2)), setup="inside_a_job", expect='"raised"'),
    "worker_at_the_hard_stop": dict(replies=[_call("web_search", {"query": "a"}, "c1"), _call("web_search", {"query": "b"}, "c2")],
                                    budget=dict(limits=Limits(model_requests=2)),
                                    caller=tool_caller.ToolCaller("spawn", 3, "c1"), expect='"raised"'),
    "lane_at_the_hard_stop": dict(replies=[_call("web_search", {"query": "a"}, "c1"), _call("web_search", {"query": "b"}, "c2")],
                                  budget=dict(limits=Limits(model_requests=2)), setup="lane", expect='"raised"'),
    # ── what reaches the executor and the cards ──
    "everything_passed_through": dict(replies=[
        _batch(("write_file", {"path": "a.md", "content": "x"}, "c1"),
               ("schedule_task", {"name": "n", "when": "every: 3600", "prompt": "p"}, "c2"),
               ("run_command", {"command": "git push origin main", "why": "to publish it"}, "c3")), Reply("Done.")],
        tools=_table("write_file", "schedule_task", "run_command"), setup="every_card", tool_timeout_s=7.5,
        caller=tool_caller.ToolCaller("host", None, "c1"), conversation_id="c1", expect='"caller": "host"'),
    "command_outside_the_sandbox": dict(replies=[
        _call("run_command", {"command": "ls", "outside_sandbox": True, "why": "it needs the keychain"}), Reply("Done.")],
        tools=_table("run_command"), setup="command_card", expect='"outside": true'),
    "command_stopped_by_the_sandbox": dict(replies=[
        _call("run_command", {"command": "ls"}, "c1"),
        _call("run_command", {"command": "ls", "outside_sandbox": True, "why": "the sandbox stopped it"}, "c2"), Reply("Done.")],
        tools=_table("run_command"), setup="command_card", answers={"run_command": _stopped_by_the_sandbox},
        expect="the sandbox stopped it"),
    "plain_script_runs_with_no_wrapper": dict(replies=[
        _call("run_command", {"command": "osascript -e 'tell application \"Notes\" to count notes'"}), Reply("Done.")],
        tools=_table("run_command"), setup="clicked_card", expect='"unwrapped": true'),
    "command_after_outside_content": dict(replies=[
        _call("web_extract", {"url": "https://example.test/a"}, "c1"), _call("run_command", {"command": "ls"}, "c2"), Reply("Done.")],
        tools=_table("web_extract", "run_command"), setup="command_card", expect='"offline": true'),
    "network_card_after_outside_content": dict(replies=[
        _call("web_extract", {"url": "https://example.test/a"}, "c1"),
        _call("run_command", {"command": "curl https://example.test/b"}, "c2"), Reply("Done.")],
        tools=_table("web_extract", "run_command"), setup="command_card", expect='"network": true'),
    "delete_outside_goes_to_the_trash": dict(replies=[
        _call("run_command", {"command": "rm -r /tmp/loop1-old", "outside_sandbox": True, "why": "it is outside"}), Reply("Done.")],
        tools=_table("run_command"), setup="command_card", expect='"trash": true'),
    "delete_in_the_sandbox_stays_a_delete": dict(replies=[
        _call("run_command", {"command": "rm -r /tmp/loop1-old"}), Reply("Done.")],
        tools=_table("run_command"), setup="command_card", expect='"delete": "sandboxed"'),
    # ── a tool's own limit, on a clock that doesn't move: 100 seconds of the turn are left ──
    "command_limit_leaves_its_reserve": dict(replies=[_call("run_command", {"command": "ls"}), Reply("Done.")],
        tools=_table("run_command"), setup="command_card", own_limit={"run_command": 600}, expect='["limit", 90.0]'),
    "command_own_limit_under_the_default": dict(replies=[_call("run_command", {"command": "ls"}), Reply("Done.")],
        tools=_table("run_command"), setup="command_card", own_limit={"run_command": 15}, expect='["limit", 15.0]'),
    "tool_own_limit_over_and_under_the_default": dict(replies=[
        _call("web_search", {"query": "a"}, "c1"), _call("read_file", {"path": "a.md"}, "c2"), Reply("Done.")],
        tools=_table("web_search", "read_file"), own_limit={"web_search": 300, "read_file": 5}, expect='["limit", 300.0]'),
    "delegating_gets_what_is_left": dict(replies=[_call("delegate_work", {"jobs": [{"method": "research", "objective": "o"}]}), Reply("Done.")],
        tools=_table("delegate_work"), answers={"delegate_work": {"ok": True}}, own_limit={"delegate_work": 300},
        expect='["limit", 100.0]'),
    # ── a job with checks ──
    "checks_ask_for_a_repair": dict(replies=[Reply("First try."), Reply("Second try.")], job=[["missing part"], []],
                                    expect="Deterministic validation failed"),
    "checks_fail_after_repairs": dict(replies=[Reply("First."), Reply("Second."), Reply("Third.")],
                                      job=[["bad one"], ["bad two"], ["bad three"]], expect="task_validation_failed"),
    "checks_on_a_streamed_answer": dict(replies=[Reply(LONG), Reply(LONG + "again"), Reply(LONG + "and again")],
                                        job=[["bad one"], ["bad two"], ["bad three"]], answer_only=True,
                                        links=["https://not-read.test/z"], expect="not-read.test/z"),
    "job_stops_on_no_progress": dict(replies=[*_searches(5), Reply("Blocked.")], tools=_table("web_search"),
                                     answers=NOTHING_FOUND, job=[[]], expect="task_no_progress"),
    "job_saved_then_no_progress": dict(replies=[
        _call("write_file", {"path": "a.md", "content": "x"}, "w0"), *_searches(5), Reply("Blocked, with the file saved.")],
        tools=_table("web_search", "write_file"), answers=NOTHING_FOUND, job=[[]], expect='"limit_reason": "task_no_progress"'),
    "job_choice_card": dict(replies=[_call("ask_user_choice", {"question": "Which?", "options": ["A", "B"]})],
                            tools=_table("ask_user_choice"), job=[], expect="task_input_required"),
    "job_error_after_text": dict(replies=[Reply(LONG, raises=_refusal(400, "bad request"))], job=[], answer_only=True,
                                 expect="model_error_after_text"),
    # ── what the provider does ──
    "status_kept_in_the_trajectory": dict(replies=[_call("web_search", {"query": "a"}), Reply("Done.")],
                                          provider=dict(APPENDS_STATUS=True), expect='"_status"'),
    "provider_clears_old_results": dict(replies=[_call("web_search", {"query": "a"}), Reply("Done.")],
                                        provider=dict(trims_context_server_side=lambda: True),
                                        history=[{"role": "user", "content": "old " * 30000},
                                                 {"role": "assistant", "content": "ok"}], expect='"ran"'),
    "rate_limited_then_answered": dict(replies=[Reply(raises=_refusal(429, "rate limited")), Reply("Answered after the wait.")],
                                       expect='"waited"'),
    "server_error_then_answered": dict(replies=[Reply(raises=_refusal(503, "overloaded")), Reply(raises=_refusal(500, "broke")),
                                                Reply("Answered after two waits.")], expect='"waited"'),
    "rate_limited_after_text": dict(replies=[Reply(LONG, raises=_refusal(429, "rate limited"))],
                                    expect="model_error_after_text"),
    "endpoint_refuses_the_protocol": dict(replies=[
        Reply(raises=_refusal(400, "messages: invalid role tool, tool_call_id is not supported")),
        Reply("Answered on the legacy rendering.")], expect="legacy request"),
    "context_overflow_compacts_once": dict(replies=[
        Reply(raises=_refusal(400, "maximum context length is 8192 tokens")), Reply("Answered after compacting.")],
        history=[{"role": "user", "content": "old " * 500}, {"role": "assistant", "content": "ok"}],
        expect="Answered after compacting."),
    "context_overflow_when_the_provider_clears": dict(replies=[
        Reply(raises=_refusal(400, "maximum context length is 8192 tokens")), Reply("Answered after compacting.")],
        provider=dict(trims_context_server_side=lambda: True),
        history=[{"role": "user", "content": "old " * 500}, {"role": "assistant", "content": "ok"}],
        expect="Answered after compacting."),
    "mcp_schema_refused": dict(replies=[
        Reply(raises=_refusal(400, "tools.1.custom.input_schema: bad schema for mcp_1__lookup")),
        _call("web_search", {"query": "a"}), Reply("Done without it.")],
        tools=[*_mcp("mcp_1__lookup"), *_table("web_search")], expect="refused its parameter schema"),
    "mcp_schema_refused_twice": dict(replies=[
        Reply(raises=_refusal(400, "tools.1.custom.input_schema: bad schema for mcp_1__lookup")),
        Reply(raises=_refusal(400, "tools.1.custom.input_schema: bad schema for mcp_2__other")), Reply("Done without them.")],
        tools=[*_mcp("mcp_1__lookup", "mcp_2__other"), *_table("web_search")], expect="every MCP tool"),
    "mcp_schema_refused_by_no_name": dict(replies=[
        Reply(raises=_refusal(400, "invalid schema in tools")), Reply("Done without them.")],
        tools=[*_mcp("mcp_1__lookup"), *_table("web_search")], provider=dict(APPENDS_STATUS=True), expect="every MCP tool"),
    "mcp_failures_get_a_hint": dict(replies=[
        _call("mcp_1__lookup", {"id": 1}, "c1"), _call("mcp_1__lookup", {"id": 2}, "c2"), Reply("Used the built-in.")],
        tools=_mcp("mcp_1__lookup"), answers={"mcp_1__lookup": {"ok": False, "error": "server said no"}},
        conversation_id="c1", expect="has failed 2 times in a row"),
    "mcp_failures_not_logged": dict(replies=[
        _call("mcp_1__lookup", {"id": 1}, "c1"), _call("mcp_1__lookup", {"id": 2}, "c2"), Reply("Used the built-in.")],
        tools=_mcp("mcp_1__lookup"), answers={"mcp_1__lookup": {"ok": False, "error": "server said no"}},
        conversation_id="c1", log_events=False, expect="has failed 2 times in a row"),
    "output_limit_raised_then_continued": dict(replies=[
        Reply("The start", finish="length"), Reply("The start again", finish="length"), Reply(" and the end.")],
        provider=dict(output_ceiling=8000, max_tokens=4000), expect="and the end."),
    "cut_answer_continued_twice": dict(replies=[
        Reply("One", finish="length"), Reply(" two", finish="length"), Reply(" three", finish="length")],
        expect="Continue exactly where it stopped"),
    "images_refused_are_read_here": dict(replies=[
        _call("desktop_look", {"app": "Notes"}), Reply(raises=_refusal(400, "this model does not support image input")),
        Reply("Read it as text.")], tools=_table("desktop_look"), setup="ocr", expect="the text this Mac read off it"),
}


@pytest.fixture(scope="module")
def _booted(tmp_path_factory):
    """One booted database to copy: the migrations take seconds, and a turn needs only a fresh file."""
    path = tmp_path_factory.mktemp("loop1") / "booted.db"

    async def boot():
        engine = db_session.build_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as connection:
            await connection.run_sync(boot_schema)
        await engine.dispose()
    asyncio.run(boot())
    return path


@pytest.fixture
async def _database(monkeypatch, tmp_path, _booted):
    path = tmp_path / "turn.db"
    shutil.copy(_booted, path)
    engine = db_session.build_engine(f"sqlite+aiosqlite:///{path}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    yield maker
    await engine.dispose()


async def _run(name, monkeypatch, database):
    spec = SCENARIOS[name]
    log: list = []
    golden._pin_workspace(monkeypatch)
    tool_loop._BAD_TOOLS.clear()         # per process: a refusal in one scenario must not reach the next
    tool_loop._REFUSES_IMAGES.clear()
    on_demand._used.clear()

    async def english():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", english)
    monkeypatch.setattr(lessons, "later", lambda coroutine: coroutine.close())   # off the reply path: not this pin's
    monkeypatch.setattr(command_sandbox, "available", lambda: True)              # the same on Linux and macOS
    monkeypatch.setattr(desktop_status, "note_step", lambda tool, _args: log.append(["island", "step", tool]))
    monkeypatch.setattr(desktop_status, "note_plan", lambda items: log.append(["island", "plan", copy.deepcopy(items)]))
    monkeypatch.setattr(agent_status, "recent_files", lambda *_args, **_own: [])  # the real ~/Arslan is not this pin's
    _watch(log, monkeypatch)
    own_limit = spec.get("own_limit", {})
    if own_limit:
        monkeypatch.setattr(eb, "time", types.SimpleNamespace(monotonic=lambda: 1000.0))
        spec = {**spec, "budget": dict(limits=Limits(wall_seconds=100))}
    for key, answer in {**ANSWERS, **spec.get("answers", {})}.items():
        monkeypatch.setitem(executors.EXECUTORS, key, _Ran(log, key, answer, timeout_s=own_limit.get(key)))
    async with database() as db:
        db.add(Setting(key="shell_confirm_policy", value="ask_all"))      # a card for every command, whatever the default
        if spec.get("streams") is False:
            db.add(Setting(key="answer_when_complete", value="true"))
        await db.commit()
    provider = types.SimpleNamespace(**spec["provider"]) if spec.get("provider") else None
    tools, later, saved = spec.get("tools", RESEARCH), spec.get("later_tools"), {"done": False}

    async def resolve():
        return copy.deepcopy(later if later and saved["done"] else tools)

    async def expected():
        return tool_loop._native_tool_schemas(await resolve(), allow_escalation=spec.get("allow_escalation", False))
    model = _Model(log, spec["replies"], provider, expected)

    kwargs = dict(system="SYS", user_content="the request", history=spec.get("history", []),
                  emit=lambda frame: log.append(["frame", copy.deepcopy(frame)]),
                  on_chunk=lambda chunk: log.append(["chunk", chunk]), resolve_tools=resolve, adapter_override=model,
                  allow_escalation=spec.get("allow_escalation", False))
    for key in ("max_tool_calls", "force_tools", "stream_without_tools", "turn_notes", "steerable", "conversation_id",
                "caller", "log_events", "tool_timeout_s"):
        if key in spec:
            kwargs[key] = spec[key]
    if "callable" in spec:
        async def reachable():
            return copy.deepcopy(spec["callable"])
        kwargs["resolve_callable"] = reachable
    _setup(spec, log, monkeypatch, saved, kwargs)
    runtime = _job(log, monkeypatch, spec) if "job" in spec else kwargs.get("progress_lane")
    budget = Budget(spec["budget"]["limits"], soft=spec["budget"].get("soft")) if spec.get("budget") else Budget()
    with eb.scope(budget):
        try:
            log.append(["returned", await tool_loop.run_native(**kwargs)])
        except AssertionError:
            raise
        except Exception as exc:  # noqa: BLE001 — what it raises is part of what is pinned
            log.append(["raised", type(exc).__name__, str(exc)])
    if runtime is not None:
        log.append(["job", {"pause_reason": runtime.pause_reason, "limit_reason": runtime.limit_reason,
                            "repairs": len(runtime.progress.validation_repairs)}])
    return log


def _watch(log, monkeypatch):
    """What a turn does that no frame shows: its limit on each call, its waits, its checkpoints and its events."""
    within = tool_loop.within

    async def limited(awaitable, timeout, **own):
        log.append(["limit", timeout])
        return await within(awaitable, timeout, **own)
    monkeypatch.setattr(tool_loop, "within", limited)
    monkeypatch.setattr(answer_salvage, "within", limited)

    async def waited(seconds):
        log.append(["waited", seconds])
    monkeypatch.setattr(model_call, "sleep", waited)
    monkeypatch.setattr(model_call, "jitter", lambda: 0.0)

    async def saved(reason):
        log.append(["execution checkpoint", reason])
    monkeypatch.setattr(execution_checkpoint, "save", saved)

    async def event(conversation_id, kind, payload, _text):
        log.append(["event", conversation_id, kind, payload])
    monkeypatch.setattr(recap_service, "log_event", event)


def _card(log, name, clicked=False):
    async def confirm(*shown, **own):
        if clicked:
            permissions.LAST_DECISION.set(types.SimpleNamespace(by="user"))
        log.append(["card", name, list(shown), own])
        return True
    return confirm


def _setup(spec, log, monkeypatch, saved, kwargs):
    setup = spec.get("setup")
    if setup == "skill_saved":
        async def propose(args, **_own):
            saved["done"] = True
            return {"ok": True, "saved": args["key"], "refresh": True}
        monkeypatch.setattr(skill_forge, "propose", propose)
    elif setup == "capability_declined":
        async def declined(_args, **_own):
            return {"ok": False, "error": "the user declined"}
        monkeypatch.setattr(capability_flow, "propose", declined)
    elif setup == "command_card":
        kwargs["confirm_command"] = _card(log, "command")
    elif setup == "clicked_card":
        kwargs["confirm_command"] = _card(log, "command", clicked=True)
    elif setup == "every_card":
        async def not_own():
            return False
        monkeypatch.setattr(tool_loop, "_writing_in_own_folder", not_own)
        kwargs.update(confirm_command=_card(log, "command"), confirm_workspace_write=_card(log, "write"),
                      confirm_schedule=_card(log, "schedule"))
    elif setup == "inside_a_job":
        monkeypatch.setattr(background_jobs, "inside_job", lambda: True)
    elif setup == "lane":
        kwargs["progress_lane"] = _runtime(log, {})
    elif setup == "presearch":
        async def classify(*_args, **_own):
            return types.SimpleNamespace(needs=True, tool="web_search", query="the pre-search")
        monkeypatch.setattr(tool_intent, "classify", classify)
    elif setup == "ocr":
        monkeypatch.setattr(ocr_fallback, "read_locally", lambda *_args, **_own: ("text on the window", "ok"))
    elif setup == "long_turn":
        clock = types.SimpleNamespace(now=1000.0)
        clock.monotonic = lambda: clock.now
        monkeypatch.setattr(eb, "time", types.SimpleNamespace(monotonic=lambda: clock.now))

        class _Slow(_Ran):
            async def execute(self, args):
                clock.now += 20 * 60
                return await super().execute(args)
        key = spec.get("slow", "web_search")
        monkeypatch.setitem(executors.EXECUTORS, key, _Slow(log, key, ANSWERS[key]))
    elif setup in ("message_meanwhile", "message_before_the_calls"):
        async def stored(_conversation, _role, content, **_own):
            log.append(["stored", content])
            return 7
        monkeypatch.setattr(memory, "add_message", stored)
        steering.open_box("steered")

        async def tell(frame):
            log.append(["told", frame])

        def message():
            steering.put("steered", steering.Steer("also this", None, {"type": "user_message"}, tell, asyncio.Queue()))

        if setup == "message_before_the_calls":
            # It arrives while the model writes its reply, so the first call of the batch is already past the check.
            answer_next = _Model._next

            async def with_a_message(self, on_text=None):
                monkeypatch.setattr(_Model, "_next", answer_next)
                message()
                return await answer_next(self, on_text)
            monkeypatch.setattr(_Model, "_next", with_a_message)
            return

        class _First(_Ran):
            told = False

            async def execute(self, args):
                if not _First.told:
                    _First.told = True
                    message()
                return await super().execute(args)
        key = spec["steer_on"]
        monkeypatch.setitem(executors.EXECUTORS, key, _First(log, key, spec.get("answers", {}).get(key, ANSWERS[key])))


def _runtime(log, spec):
    check = types.SimpleNamespace(evaluator="auto", model_dump=lambda **_own: {"kind": "mentions", "target": "x"})

    async def checkpoint(reason):
        log.append(["checkpoint", reason])

    async def execute_tool(_key, args, execute):
        return await execute(args)
    return types.SimpleNamespace(
        spec=types.SimpleNamespace(acceptance=[check] if "job" in spec else [], locale="en"), progress=_Progress(),
        checkpoint=checkpoint, execute_tool=execute_tool, pause_reason=None, limit_reason=None, closed=False, task_id="t1")


def _job(log, monkeypatch, spec):
    reports = list(spec["job"])
    runtime = _runtime(log, spec)
    monkeypatch.setattr(task_service, "current", lambda: runtime)
    monkeypatch.setattr(task_service, "answer_only", lambda: spec.get("answer_only", False))

    async def validate(_runtime, output, _trace, **_own):
        log.append(["validated", output])
        return {"failures": reports.pop(0)}
    monkeypatch.setattr(task_validation, "validate_output", validate)
    monkeypatch.setattr(task_validation, "failures", lambda report: report["failures"])
    monkeypatch.setattr(task_validation, "unverified_links", lambda *_args: spec.get("links", []))
    monkeypatch.setattr(task_validation, "failure_output", lambda output, report, _locale: (
        f"{output}\n[checks failed: {report['failures']}]"))
    return runtime


def _short(value):
    """A long string stays exact by its hash, so the pins stay readable and small."""
    if isinstance(value, str) and len(value) > 1500:
        return f"{value[:300]}…<{len(value)} characters, sha256 {hashlib.sha256(value.encode()).hexdigest()[:16]}>…{value[-300:]}"
    if isinstance(value, dict):
        return {key: _short(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_short(item) for item in value]
    return value


def _text(log) -> str:
    return json.dumps(_short(log), ensure_ascii=False, indent=1, sort_keys=True, default=str) + "\n"


@pytest.mark.parametrize("name", list(SCENARIOS))
async def test_a_turn_does_what_it_did(name, monkeypatch, _database):
    log = await _run(name, monkeypatch, _database)
    text = _text(log)
    path = GOLDEN / f"{name}.json"
    if os.environ.get("ARSLAN_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert SCENARIOS[name]["expect"] in json.dumps(log, ensure_ascii=False, default=str), (
        f"{name} no longer reaches {SCENARIOS[name]['expect']!r}. If you meant it, change `expect` in SCENARIOS and "
        f"commit the new JSON: {REGENERATE}")
    assert path.exists(), f"{name} has no pin yet: {REGENERATE}"
    assert text == path.read_text(encoding="utf-8"), (
        f"what the turn did changed: {name}. If you meant it, commit the new JSON, so the diff shows the change: "
        f"{REGENERATE}")


def test_every_pin_has_its_scenario():
    assert {path.stem for path in GOLDEN.glob("*.json")} == set(SCENARIOS)
