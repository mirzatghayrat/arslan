"""K8a: the answer goes out while it is written; guards correct afterwards (card K8; ⓪Plan's Q1–Q4).

Driven through the real LLMAdapter and OpenAIProvider on a DeepSeek-shaped streaming mock, so the text
reaches the loop through C1's hook exactly as in production.
- A step's text is held until it passes the window (160 characters): a short answer is judged whole, as
  before; a tool call inside the window makes it narration (a note). Past the window it goes out as it
  arrives, minus the tail that could still open a tool call written as text (never shown) or a host
  bookkeeping block (dropped).
- Past the window, a guard appends a correction and the next step's text follows it.
- The stored answer is exactly the joined chunks (the window, the phone and the run record join them).
- Once text went out, a failed request is never resent: the turn ends with "interrupted", recorded as a
  failure. Before that, retries are as before. A cut answer is continued, never resent.
- An answer that keeps claiming what no tool did is sent back at most twice (⓪Plan Q4).
"""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from arslan.llm.adapter import LLMAdapter
from server.orchestrator import tool_loop
from sqlalchemy import select

from server.db.models import CompanionTask, Run
from server.services import host_run, runtime_messages, task_service, task_validation
from server.services import personal_context as pc
import server.db.session as db_session
from tests.llm.test_stream_assembly_s7 import BASE, delta, finish, provider, sse
from tests.server.test_promise_guard import maker  # noqa: F401 — a chat database for arslan.handle_user_message

PROSE = ("The river rises in the hills and runs north through three valleys before it meets the sea; "
         "its water feeds farms, two towns and a long line of old mills along the way. ") * 3
CORRECTION = runtime_messages.render("stream_correction", "en")
INTERRUPTED = runtime_messages.render("stream_interrupted", "en")


def _reply(text="", *, size=20, tool=None, stop="stop", done=True):
    frames = [delta(role="assistant")] + [delta(content=text[i:i + size]) for i in range(0, len(text), size)]
    if tool:
        frames.append(delta(tool_calls=[{"index": 0, "id": "c1", "type": "function",
                                         "function": {"name": tool[0], "arguments": json.dumps(tool[1])}}]))
    if stop:
        frames.append(finish("tool_calls" if tool else stop))
    return sse(*frames, done=done)


class _Counted(httpx.AsyncByteStream):
    """One SSE event at a time, counted, so a test can tell what had arrived when a chunk went out."""

    def __init__(self, body: bytes, sent: list):
        self.events, self.sent = [e for e in body.split(b"\n\n") if e], sent

    async def __aiter__(self):
        for event in self.events:
            self.sent.append(event)
            yield event + b"\n\n"
            await asyncio.sleep(0)


@pytest.fixture
def turn(execution_db, monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    monkeypatch.setattr(runtime_messages, "selected_locale", _en)

    async def run(replies, *, tools=(), executors=None, sent=None, in_task=False):
        bodies = []

        def handler(request):
            body = json.loads(request.content)
            bodies.append(body)
            reply = replies[len(bodies) - 1]
            if not body.get("stream"):                    # a non-streamed helper call (salvage)
                return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": reply},
                                                              "finish_reason": "stop"}], "usage": {}})
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  stream=_Counted(reply, sent if sent is not None else []))
        adapter = LLMAdapter("openai", "deepseek-v4-flash", api_key="k", base_url=BASE)
        adapter._provider = provider(handler)
        monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
        from server.registry import executors as registry
        for key, executor in (executors or {}).items():
            monkeypatch.setitem(registry.EXECUTORS, key, executor)

        async def resolve():
            return [{"key": key, "description": key} for key in tools]
        chunks, events = [], []

        async def go():
            return await tool_loop.run_native(system="S", user_content="question", history=[], emit=events.append,
                                              on_chunk=chunks.append, resolve_tools=resolve)
        if not in_task:
            return await go(), chunks, events, bodies
        # A chat turn as production runs it: run_turn (acceptance left to its default) around host_run.
        held = {}

        async def function(conversation, message, emit):
            async def body(sink):
                held["result"] = await go()
                return held["result"]["final"]
            return await host_run.execute(conversation, message, emit, body)
        with pc.bind(pc.TaskMemoryContext(task_id="live-task", run_id="initial", conversation_id="live")):
            await task_service.run_turn(function, "live", "question", events.append)
        return held["result"], chunks, events, bodies
    return run


async def _en():
    return "en"


class _Search:
    async def execute(self, args):
        return {"ok": True, "results": ["hit"]}


async def test_a_long_answer_goes_out_while_it_is_written(turn):
    sent, at_first = [], []
    original = tool_loop._TurnText.show

    def show(self, text):
        if not self.parts:
            at_first.append(len(sent))
        original(self, text)
    tool_loop._TurnText.show = show
    try:
        result, chunks, _, _ = await turn([_reply(PROSE)], sent=sent)
    finally:
        tool_loop._TurnText.show = original
    total = len([e for e in _reply(PROSE).split(b"\n\n") if e])
    assert at_first and at_first[0] < total                       # out before the model finished
    assert (at_first[0] - 1) * 20 >= tool_loop._DEFERRAL_MAX       # and not before the window passed
    assert "".join(chunks) == result["final"] and result["final"].strip() == PROSE.strip()


async def test_narration_before_a_tool_call_stays_a_note(turn):
    result, chunks, events, _ = await turn([_reply("Let me check that.", tool=("web_search", {"query": "q"})),
                                            _reply(PROSE)], tools=("web_search",), executors={"web_search": _Search()})
    assert any(e.get("type") == "note" and "Let me check" in e.get("text", "") for e in events)
    assert "Let me check" not in "".join(chunks) and result["final"].strip() == PROSE.strip()


async def test_a_short_promise_is_sent_back_with_nothing_shown(turn):
    result, chunks, _, bodies = await turn([_reply("让我搜索一下。"), _reply(PROSE)], tools=("web_search",))
    assert "".join(chunks).strip() == PROSE.strip() == result["final"].strip() and len(bodies) == 2


async def test_past_the_window_a_claim_is_corrected_after_it(turn):
    claim = "I searched the web and found it. " + PROSE
    result, chunks, _, bodies = await turn([_reply(claim), _reply(PROSE)], tools=("web_search",))
    joined = "".join(chunks)
    assert joined == result["final"]
    assert joined.startswith(claim.rstrip()[:100]) and f"\n\n{CORRECTION}\n\n" in joined
    assert joined.rstrip().endswith(PROSE.rstrip()[-60:])
    assert "lacks a successful web_search receipt" in json.dumps(bodies[1]["messages"])


@pytest.mark.parametrize("marker", [
    '<tool_call>{"name": "x"}</tool_call>', '</tool_call>', "<｜｜DSML｜｜tool_calls>", "｜DSML｜",
    "<｜tool▁calls▁begin｜>", '{"tool": "web_search", "args": {}}', '{ "tool" : "x"}',
    '{"functionCall": {"name": "x"}}', '{"escalate": {"kind": "data"}}', '{"query": "x", "tool": "web_search"}',
    '{"query": "' + "a long query " * 20 + '", "tool": "web_search"}'])      # longer than the tail kept back
async def test_a_tool_call_written_as_text_never_goes_out_one_char_at_a_time(turn, marker):
    text = PROSE + marker + " and some words after it."
    result, chunks, _, _ = await turn([_reply(text, size=1), _reply(PROSE)], tools=("web_search",))
    joined = "".join(chunks)
    assert not tool_loop._embeds_protocol(joined) and joined == result["final"]
    assert joined.startswith(PROSE[:100]) and CORRECTION in joined


async def test_host_bookkeeping_is_dropped_from_what_goes_out(turn):
    text = PROSE + "<agent_status>tool calls: 2</agent_status>" + " The rest of the answer follows here." * 6
    result, chunks, _, _ = await turn([_reply(text, size=7)])
    joined = "".join(chunks)
    assert "agent_status" not in joined and "tool calls: 2" not in joined and joined == result["final"]
    assert "The rest of the answer" in joined


async def test_a_long_bookkeeping_block_is_held_until_it_closes(turn):
    block = "<agent_status>" + "step 1: looked at the folder; " * 8 + "</agent_status>"   # longer than the tail
    text = PROSE + block + " The rest of the answer follows here." * 6
    result, chunks, _, _ = await turn([_reply(text, size=5)])
    joined = "".join(chunks)
    assert "agent_status" not in joined and "looked at the folder" not in joined and joined == result["final"]


async def test_text_that_went_out_before_a_tool_call_stays_in_the_answer_not_a_note(turn):
    result, chunks, events, _ = await turn([_reply(PROSE, tool=("web_search", {"query": "q"})),
                                            _reply("And the search agrees. " * 8)],
                                           tools=("web_search",), executors={"web_search": _Search()})
    joined = "".join(chunks)
    assert joined.startswith(PROSE[:100]) and joined == result["final"]
    assert not any(e.get("type") == "note" and "river" in e.get("text", "") for e in events)


async def test_an_error_that_is_not_retried_after_text_went_out_also_ends_interrupted(turn, monkeypatch):
    from server.orchestrator import model_call
    monkeypatch.setattr(model_call, "MAX_SERVER_RETRIES", 0)     # the failure reaches _model_call's recovery
    result, chunks, _, bodies = await turn([_reply(PROSE, stop=None, done=False), _reply(PROSE)])
    assert len(bodies) == 1 and result["final"].endswith(INTERRUPTED) and "".join(chunks) == result["final"]


def test_what_is_held_back_stays_bounded():
    shown = []
    step = tool_loop._StepStream(tool_loop._TurnText(shown.append))
    for ch in PROSE * 2:
        step.feed(ch)
        assert len(step.pending) <= tool_loop._STREAM_HOLD
    for ch in '{"a": "' + "x" * 3000:                             # a JSON object still open
        step.feed(ch)
        assert len(step.pending) <= tool_loop._JSON_HOLD + tool_loop._STREAM_HOLD


async def test_an_error_after_text_went_out_ends_with_interrupted_and_a_failure(turn):
    holder = {}
    host_run._failure.set(holder)
    cut = _reply(PROSE, stop=None, done=False)                   # the connection ends mid-reply
    result, chunks, _, bodies = await turn([cut, _reply(PROSE)])
    joined = "".join(chunks)
    assert len(bodies) == 1 and joined == result["final"] and joined.endswith(INTERRUPTED)
    assert result["stop_reason"] == "model_error_after_text" and holder["kind"] == "model_error_after_text"


async def test_an_error_before_anything_went_out_is_retried_as_before(turn):
    cut = _reply(PROSE[:100], stop=None, done=False)
    result, chunks, _, bodies = await turn([cut, _reply(PROSE)])
    assert len(bodies) == 2 and "".join(chunks) == result["final"] and result["final"].strip() == PROSE.strip()


async def test_a_cut_answer_is_continued_never_resent(turn):
    result, chunks, _, bodies = await turn([_reply(PROSE, stop="length"), _reply(" And that is the end.")])
    joined = "".join(chunks)
    assert joined == result["final"] and joined.rstrip().endswith("And that is the end.")
    assert bodies[1]["messages"][-1]["content"] == tool_loop.CONTINUE_PROMPT


async def test_an_answer_that_keeps_claiming_is_sent_back_at_most_twice(turn):
    claim = _reply("I searched the web: it is 42.")
    result, _, _, bodies = await turn([claim, claim, claim, "fallback"], tools=("web_search",))
    streamed = [b for b in bodies if b.get("stream")]
    assert len(streamed) == tool_loop._UNVERIFIED_BOUNCES + 1 and "42" not in (result["final"] or "")


async def test_a_bad_link_after_text_went_out_is_listed_not_rewritten(turn, monkeypatch, execution_db):
    link = "/api/v1/runs/5/artifacts/report.md"
    report = {"checks": [], "artifacts": [{"url": link, "status": "failed", "code": "missing", "check_id": "a"}]}

    async def validate(*a, **k):
        return report
    monkeypatch.setattr(task_validation, "validate_output", validate)
    answer = PROSE + f" The report is at {link} for you."
    result, chunks, _, _ = await turn([_reply(answer), _reply(PROSE + f" See {link}.")], in_task=True)
    joined = "".join(chunks)
    listing = runtime_messages.render("links_not_verified", "en", links=link)
    assert joined == result["final"] and joined.count(link) == 3 and joined.count(listing) == 1
    async with execution_db() as db:
        task = (await db.execute(select(CompanionTask))).scalar_one()
    assert task.pause_reason == "task_validation_failed"


async def test_a_new_bad_link_in_the_last_answer_is_listed_too(turn, monkeypatch):
    a, b, c = (f"/api/v1/runs/5/artifacts/{name}.md" for name in ("a", "b", "c"))

    def failed(*links):
        return {"checks": [], "artifacts": [{"url": link, "status": "failed", "code": "missing", "check_id": link}
                                            for link in links]}
    reports = iter([failed(a), failed(a, b), failed(a, b)])     # the third repeats: no more repairs

    async def validate(*args, **kwargs):
        return next(reports)
    monkeypatch.setattr(task_validation, "validate_output", validate)
    result, chunks, _, _ = await turn([_reply(PROSE + f" See {a} here."), _reply(PROSE + f" See {b} here."),
                                       _reply(PROSE + f" See {c} here.")], in_task=True)
    joined = "".join(chunks)
    assert joined == result["final"]
    for link in (a, b, c):                                      # each listed once, the last one at the end
        assert joined.count(runtime_messages.render("links_not_verified", "en", links=link)) <= 1
    assert joined.rstrip().endswith(c)


async def test_an_interrupted_answer_records_a_failed_run_and_task(turn, execution_db):
    result, chunks, _, _ = await turn([_reply(PROSE, stop=None, done=False)], in_task=True)
    assert "".join(chunks) == result["final"] and result["final"].endswith(INTERRUPTED)
    async with execution_db() as db:
        task = (await db.execute(select(CompanionTask))).scalar_one()
        recorded = (await db.execute(select(Run))).scalar_one()
    assert recorded.status == "failed" and recorded.error_kind == "model_error_after_text"
    assert task.phase != "succeeded" and task.pause_reason == "model_error_after_text"


async def test_whether_a_turn_streams(execution_db, monkeypatch):
    a = SimpleNamespace(_provider=SimpleNamespace(model="deepseek-v4-flash", base_url=BASE))
    assert await tool_loop._streams_answer(a, None) is True
    assert await tool_loop._streams_answer(a, object()) is False          # explicit criteria, jobs
    token = task_service._answer_only.set(True)
    try:
        assert await tool_loop._streams_answer(a, object()) is True       # only "an answer was delivered"
    finally:
        task_service._answer_only.reset(token)
    monkeypatch.setattr(tool_loop, "BUFFERED_MODELS", frozenset({"deepseek-v4-flash"}))
    assert await tool_loop._streams_answer(a, None) is False


async def test_answers_only_when_complete_is_the_old_path(turn, monkeypatch):
    from server.services import settings_service

    async def yes(db):
        return True
    monkeypatch.setattr(settings_service, "answer_when_complete", yes)
    sent, at_first = [], []
    original = tool_loop._reveal_streamed

    async def reveal(text, on_chunk):
        at_first.append(len(sent))
        await original(text, on_chunk)
    monkeypatch.setattr(tool_loop, "_reveal_streamed", reveal)
    result, chunks, _, _ = await turn([_reply(PROSE)], sent=sent)
    total = len([e for e in _reply(PROSE).split(b"\n\n") if e])
    assert at_first == [total] and "".join(chunks) == result["final"]   # shown only once the model finished


def test_nothing_found_is_not_a_search_claim():
    assert not tool_loop._claims_search("没查到相关结果") and not tool_loop._claims_search("未查到")
    assert tool_loop._claims_search("查到了三条")


async def test_text_that_went_out_before_a_choice_card_is_kept(maker, monkeypatch):  # noqa: F811
    """A step that wrote past the window and then asked the user to choose: the text went out, so the
    chat stores it (in its bubble) with the question, instead of a card-only turn that drops it."""
    from server.db.models import ArslanMessage
    from server.orchestrator import arslan
    clarify = {"question": "Which one?", "options": [{"label": "A"}, {"label": "B"}]}

    async def run_native(**kwargs):
        kwargs["on_chunk"](PROSE)
        return {"final": PROSE, "clarify": clarify, "escalation": None, "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    events = []
    await arslan.handle_user_message("main", "question", events.append)
    end = next(e for e in events if e["type"] == "stream_end")
    async with db_session.AsyncSessionLocal() as db:
        stored = [m for m in (await db.execute(select(ArslanMessage))).scalars().all() if m.role == "arslan"]
    assert end["message_id"] is not None and stored[-1].id == end["message_id"]
    assert stored[-1].display_content == PROSE and stored[-1].content.endswith("- A\n- B")
    assert any(e["type"] == "clarify_options" for e in events)
