"""K8a follow-up (user report via ①iOS, 2026-11-03): one Arslan message showed the same answer four times, each
after "Correction: part of the answer above was not right; the corrected answer follows."

- A guard that sends back text which already went out replaces it; it no longer follows it. The turn emits
  `stream_restart` with a label; the window folds what went out into a collapsed earlier draft, the Bridge drops it,
  and the stored answer, the run record and the phone keep only what follows.
- The label is in the language of the text it replaces, not the interface language (the report's thread was in
  Chinese and the line was in English).
- The bounce itself was wrong: the first answer said 说明是怎么查到的 ("say how it was found"), and the
  claimed-search guard read 查到 as a claim to have searched the web. Each rewrite said the same, so it went back
  twice, and the third was a context-free salvage. Arslan's own reads (memory, a command, a file) find things too:
  查到 claims no web search. 不需要搜索了 ("no search was needed") is no claim either.

Driven through the real LLMAdapter on a DeepSeek-shaped streaming mock, as test_k8a_streaming. Text is synthetic.
"""
import json

import httpx
import pytest

from arslan.llm.adapter import LLMAdapter
from server.orchestrator import tool_loop
from server.services import host_run, run_recorder, runtime_messages, turn_journal
from tests.llm.test_stream_assembly_s7 import BASE, provider
from tests.server.test_k8a_streaming import PROSE, _reply

ZH = ("对，可以做到。只要你要求，它每次都能把依据、解释和风险讲清楚，这两件事并不冲突。"
      "按风险分开处理：只读的查询直接做，结果里带一行依据；会改状态的操作，动手前先说一句依据和风险。") * 2
HOW_FOUND = ZH + "所有结论都说明是怎么查到的，以及哪些没核对。"


@pytest.fixture
def turn(execution_db, monkeypatch):
    """One run_native turn; every frame and chunk in one ordered log."""
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)

    async def en():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", en)       # the interface is in English

    async def run(replies, *, tools=(), executors=None):
        bodies = []

        def handler(request):
            body = json.loads(request.content)
            bodies.append(body)
            reply = replies[len(bodies) - 1]
            if not body.get("stream"):                    # a non-streamed helper call (salvage)
                return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": reply},
                                                              "finish_reason": "stop"}], "usage": {}})
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=reply)
        adapter = LLMAdapter("openai", "deepseek-v4-flash", api_key="k", base_url=BASE)
        adapter._provider = provider(handler)
        monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
        from server.registry import executors as registry
        for key, executor in (executors or {}).items():
            monkeypatch.setitem(registry.EXECUTORS, key, executor)

        async def resolve():
            return [{"key": key, "description": key} for key in tools]
        log: list[dict] = []
        result = await tool_loop.run_native(
            system="S", user_content="question", history=[], emit=log.append, resolve_tools=resolve,
            on_chunk=lambda c: log.append({"type": "stream_chunk", "content": c}))
        return result, log, bodies
    return run


def shown(log: list[dict]) -> str:
    """What a joiner keeps: the restart's `keep`, then the chunks after it."""
    text = ""
    for event in log:
        if event["type"] == "stream_restart":
            text = event["keep"]
        elif event["type"] == "stream_chunk":
            text += event["content"]
    return text


def restarts(log: list[dict]) -> list[dict]:
    return [e for e in log if e["type"] == "stream_restart"]


async def test_run_492_saying_how_a_conclusion_was_found_is_not_sent_back(turn):
    result, log, bodies = await turn([_reply(HOW_FOUND)], tools=("web_search",))
    assert len(bodies) == 1 and not restarts(log)
    assert result["final"] == shown(log) == HOW_FOUND


@pytest.mark.parametrize("text", ["说明是怎么查到的", "查到了三条", "我在记忆里查到你偏好直接动手",
                                  "这个问题不需要搜索了", "不用搜索了", "我没有搜索了", "无需再搜索了",
                                  "不用再搜索了", "不用去搜索了", "网上没查到相关结果"])
def test_no_web_search_claimed(text):
    assert not tool_loop._claims_search(text)


@pytest.mark.parametrize("text", ["我搜索了三个网站", "刚才搜索了一下", "I searched the web", "我已搜过",
                                  "我在网上查到了最新价格", "网上查到", "联网查到的汇率是 7.1", "通过搜索查到了三篇"])
def test_a_web_search_claimed(text):
    assert tool_loop._claims_search(text)


async def test_a_correction_replaces_what_went_out(turn):
    claim = "I searched the web and found it. " + PROSE
    result, log, bodies = await turn([_reply(claim), _reply(PROSE)], tools=("web_search",))
    [restart] = restarts(log)
    before = "".join(e["content"] for e in log[:log.index(restart)] if e["type"] == "stream_chunk")
    assert before.startswith(claim[:100])                               # it went out, then was replaced
    assert restart["label"] == runtime_messages.render("stream_correction", "en") and restart["keep"] == ""
    assert result["final"] == shown(log) and result["final"].strip() == PROSE.strip()
    assert "searched the web" not in result["final"] and restart["label"] not in result["final"]
    assert "lacks a successful web_search receipt" in json.dumps(bodies[1]["messages"])


async def test_three_bounces_leave_one_answer_labelled_in_its_own_language(turn):
    claim = _reply("我搜索了网页，结论如下。" + ZH)
    result, log, bodies = await turn([claim, claim, claim, "最后的回答。"], tools=("web_search",))
    assert len(restarts(log)) == tool_loop._UNVERIFIED_BOUNCES + 1
    label = runtime_messages.render("stream_correction", "zh")
    assert all(r["label"] == label for r in restarts(log))               # the thread's language, not the UI's
    assert result["final"] == shown(log) == "最后的回答。"
    assert ZH[:20] not in result["final"] and label not in result["final"]


async def test_a_restart_before_anything_went_out_says_nothing(turn):
    result, log, bodies = await turn([_reply("让我搜索一下。"), _reply(PROSE)], tools=("web_search",))
    assert len(bodies) == 2 and not restarts(log) and result["final"].strip() == PROSE.strip()


def test_the_label_language():
    t = tool_loop._label_locale
    assert (t(ZH), t("ただいま確認しました。結果です。"), t("The river rises in the hills and runs north.")) == \
        ("zh", "ja", "en")
    assert t("Der Fluss ist lang und die Stadt ist alt.") == "de" and t("12345") is None


async def test_the_run_record_keeps_only_the_answer_after_a_restart(execution_db):
    async def body(emit):
        emit({"type": "stream_chunk", "content": "step one. "})
        emit({"type": "stream_chunk", "content": "draft"})
        emit({"type": "stream_restart", "label": "x", "keep": "step one. "})
        emit({"type": "stream_chunk", "content": "answer"})
        return None                                     # no final text: the run record joins what went out
    await host_run.execute("restart-run", "question", lambda ev: None, body)
    from sqlalchemy import select

    from server.db.models import Run
    async with execution_db() as db:
        run = (await db.execute(select(Run))).scalar_one()
    assert run.final_output == "step one. answer"


def test_the_partial_checkpoint_keeps_only_what_follows_a_restart():
    events = [{"type": "stream_chunk", "content": "draft"}, {"type": "stream_restart", "label": "x"},
              {"type": "stream_chunk", "content": "an"}, {"type": "stream_chunk", "content": "swer"}]
    assert run_recorder.shown_text(events) == "answer"


def test_a_window_that_reattaches_replays_the_restart():
    journal = turn_journal.begin("restart-journal")
    tee = journal.tee(lambda ev: None)
    frames = [{"type": "stream_chunk", "content": "draft"}, {"type": "stream_restart", "label": "x"},
              {"type": "stream_chunk", "content": "answer"}]
    for frame in frames:
        tee(frame)
    try:
        assert turn_journal.snapshot("restart-journal") == frames
    finally:
        turn_journal._active.clear()


class _Search:
    async def execute(self, args):
        return {"ok": True, "results": [{"title": "t", "snippet": "s", "url": "https://example.com"}]}


LATER = ("The figures for each valley follow, with the farms, the towns and the mills listed in the order the "
         "river reaches them on its way north to the sea. ") * 2


async def test_a_restart_keeps_what_earlier_steps_showed(turn):
    """#694 review, finding 1: step 1's text went out before a tool call and stays; only step 2's goes."""
    result, log, _ = await turn([_reply(PROSE, tool=("web_search", {"query": "q"})),
                                 _reply("The chart is ready. " + LATER), _reply(LATER)],
                                tools=("web_search",), executors={"web_search": _Search()})
    [restart] = restarts(log)
    assert restart["keep"].strip() == PROSE.strip()
    assert result["final"] == shown(log)
    assert result["final"].startswith(PROSE.strip()[:100]) and result["final"].rstrip().endswith(LATER.strip()[-60:])
    assert "chart is ready" not in result["final"]


@pytest.mark.parametrize("last", ["", "I searched the web: the answer is 42."])
async def test_with_no_real_replacement_what_was_shown_stays_with_one_note(turn, last):
    """#694 review, finding 2: the salvage gives nothing usable (empty, or a claim again): the user keeps what they
    saw, with one note in its language, never the generic miss line."""
    claim = _reply("I searched the web and found it. " + PROSE)
    result, log, _ = await turn([claim, claim, claim, last], tools=("web_search",))
    note = runtime_messages.render("stream_unverified_note", "en")
    miss = runtime_messages.render("chat_miss", "en")
    assert result["final"] == shown(log)
    assert result["final"].count(note) == 1 and result["final"].rstrip().endswith(note)
    assert PROSE.strip()[:100] in result["final"] and miss not in result["final"]
    assert len(restarts(log)) == tool_loop._UNVERIFIED_BOUNCES       # the last bounce replaced nothing


async def test_the_note_is_in_the_language_of_what_stays(turn):
    claim = _reply("我搜索了网页，结论如下。" + ZH)
    result, _, _ = await turn([claim, claim, claim, ""], tools=("web_search",))
    assert result["final"].rstrip().endswith(runtime_messages.render("stream_unverified_note", "zh"))


async def test_a_bounce_whose_next_step_is_held_back_replaces_at_the_end(turn):
    """The restart waits for the text that replaces it: a short rewrite (held, then shown whole) still replaces."""
    claim = "I searched the web and found it. " + PROSE
    result, log, _ = await turn([_reply(claim), _reply("Forty-two.")], tools=("web_search",))
    assert len(restarts(log)) == 1 and result["final"] == shown(log) == "Forty-two."


def test_a_job_never_passes_a_restart_to_the_chat():
    """#694 review, finding 5: a job's frames never reach the conversation's own reply."""
    from server.services import background_jobs
    sent = []
    job = background_jobs.Job.__new__(background_jobs.Job)
    sink = background_jobs._job_sink(job, sent.append)
    sink({"type": "stream_restart", "label": "x", "keep": ""})
    assert sent == []


def test_a_kept_prefix_survives_in_the_run_record():
    events = [{"type": "stream_chunk", "content": "step one. "}, {"type": "stream_chunk", "content": "bad"},
              {"type": "stream_restart", "label": "x", "keep": "step one. "}, {"type": "stream_chunk", "content": "good"}]
    assert run_recorder.shown_text(events) == "step one. good"
