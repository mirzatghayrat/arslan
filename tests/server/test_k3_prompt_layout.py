"""K3 (docs/plans/0162/K3-prompt-layout-cache.md): the system prompt is static, the turn's context
rides at the start of its request.

What changes from turn to turn (facts, summary, knowledge, the MCP line, the reply language, the
time, a resumed task's notes) goes in one block at the start of this turn's user message, marked as
reference and never saved. The system and the tool table then stay the same bytes from turn to turn,
so Claude's cache entry for them (breakpoint ①) is read instead of rewritten every turn.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

import server.db.session as db_session
from arslan.llm import param_heal, request_policy
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from server.db.models import ArslanMessage
from server.orchestrator import arslan, tool_loop, turn_context
from server.services import turn_facts
from tests.llm.test_k1b_anthropic_context import END
from tests.server.test_arslan_loop import maker, settle_after_turn  # noqa: F401 — the fixture

OPEN = turn_context.OPEN


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    param_heal.forget()

    async def nothing(conversation_id, message):
        return []
    monkeypatch.setattr(turn_facts, "extract", nothing)
    yield
    param_heal.forget()


def _claude(monkeypatch) -> list[dict]:
    sent: list[dict] = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=END)
    adapter = LLMAdapter("anthropic", "claude-opus-5-5")
    adapter._provider = AnthropicProvider("claude-opus-5-5", api_key="k", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    return sent


def _vary(monkeypatch, *, facts: str, now: str):
    """This turn's facts (a chat turn reads them through personal_context) and clock."""
    from server.services import personal_context

    async def assemble(query="", **kwargs):
        return SimpleNamespace(text=facts)

    async def record(result):
        return None
    monkeypatch.setattr(personal_context, "assemble", assemble)
    monkeypatch.setattr(personal_context, "record", record)
    monkeypatch.setattr(arslan, "_now_line", lambda: now)


def _request_text(body: dict) -> str:
    content = body["messages"][-1]["content"]
    return content if isinstance(content, str) else "".join(b.get("text", "") for b in content)


async def test_system_and_tools_are_the_same_bytes_from_turn_to_turn(maker, monkeypatch):  # noqa: F811
    sent = _claude(monkeypatch)
    _vary(monkeypatch, facts="Known facts: likes tea", now="\n\nCurrent date: 2026-10-20 08:00 UTC (Tuesday).")
    await arslan.handle_user_message("main", "Which book should I read next after this one?", lambda e: None)
    await settle_after_turn()
    _vary(monkeypatch, facts="Known facts: likes coffee", now="\n\nCurrent date: 2026-12-31 23:00 UTC (Thursday).")
    await arslan.handle_user_message("main", "下一本读什么好?", lambda e: None)
    await settle_after_turn()
    first, second = sent
    assert json.dumps(first["system"]) == json.dumps(second["system"])
    assert json.dumps(first["tools"]) == json.dumps(second["tools"])
    for poison in ("likes tea", "likes coffee", "2026-10-20", "2026-12-31", "Reply language for this turn"):
        assert poison not in json.dumps(first["system"])
    one, two = _request_text(first), _request_text(second)
    assert one.startswith(OPEN) and two.startswith(OPEN)
    assert "likes tea" in one and "2026-10-20" in one and "Reply language for this turn: English." in one
    assert "likes coffee" in two and "2026-12-31" in two and "Reply language for this turn: Chinese." in two
    assert one.endswith("Which book should I read next after this one?") and two.endswith("下一本读什么好?")


async def test_the_turn_context_is_never_saved_or_replayed(maker, monkeypatch):  # noqa: F811
    sent = _claude(monkeypatch)
    _vary(monkeypatch, facts="Known facts: likes tea", now="\n\nCurrent date: 2026-10-20 08:00 UTC (Tuesday).")
    await arslan.handle_user_message("main", "first question", lambda e: None)
    await arslan.handle_user_message("main", "second question", lambda e: None)
    await settle_after_turn()
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(ArslanMessage).order_by(ArslanMessage.id))).scalars().all()
    assert [(r.role, r.content) for r in rows if r.role == "user"] == [("user", "first question"),
                                                                        ("user", "second question")]
    # The second turn's history carries the first request as the user wrote it.
    history_texts = [m["content"] if isinstance(m["content"], str) else m["content"][0]["text"]
                     for m in sent[1]["messages"][:-1]]
    assert history_texts[0] == "first question"
    assert all(OPEN not in text for text in history_texts)


def test_the_context_block_says_what_it_is_and_keeps_todays_order(monkeypatch):
    monkeypatch.setattr(arslan, "_now_line", lambda: "\n\nNOW")
    block = arslan._turn_context(addendum="RESUME", facts="FACTS", summary="SUMMARY", kb_block="\n\nKB",
                                 mcp_line="\n\nMCP", language="\n\nLANG")
    assert block.startswith(OPEN + "\n") and block.endswith("\n" + turn_context.CLOSE)
    assert "not the user's words" in OPEN
    order = [block.index(piece) for piece in ("RESUME", "FACTS", "SUMMARY", "KB", "MCP", "LANG", "NOW")]
    assert order == sorted(order)


def test_the_system_is_the_static_prefix_plus_a_route():
    assert str(arslan._build_answer_system()) == arslan._ANSWER_STABLE_PREFIX
    background = arslan._build_answer_system(route=arslan.BACKGROUND_SYSTEM)
    assert background.stable == arslan._ANSWER_STABLE_PREFIX and background.volatile == arslan.BACKGROUND_SYSTEM


async def test_background_work_keeps_its_route_in_the_system_and_five_minute_caching(monkeypatch):
    seen = {}

    async def fake_run_native(*, system, user_content, on_chunk, **kw):
        seen.update(system=str(system), user=user_content, long=request_policy.long_prompt_cache.get())
        on_chunk("ok")
        return {"final": "ok", "tool_trace": []}

    async def fake_context(conversation_id, **kwargs):
        return {"summary": "SUMMARY-XYZ", "history": [{"role": "user", "content": "do it in the background"}]}

    async def facts_text(include_sensitive=False):
        return "FACTS-XYZ"
    monkeypatch.setattr(tool_loop, "run_native", fake_run_native)
    monkeypatch.setattr(arslan.memory, "assemble_working_context", fake_context)
    monkeypatch.setattr(arslan.memory, "facts_text", facts_text)

    class Confirm:
        command = workspace_write = schedule = None
    with request_policy.prompt_cache(long=True):        # started from inside a chat turn
        await arslan.background_body("c-bg", "copy the invoices", lambda e: None, Confirm())
    assert seen["system"] == str(arslan._build_answer_system(route=arslan.BACKGROUND_SYSTEM))
    assert seen["user"].startswith(OPEN) and seen["user"].endswith("copy the invoices")
    assert "FACTS-XYZ" in seen["user"] and "SUMMARY-XYZ" in seen["user"]
    assert seen["long"] is False


def test_tools_are_sorted_by_name_and_escalate_stays_last():
    wired = [{"key": k, "description": k} for k in ("web_search", "attach_file", "recall", "mcp_2__z", "mcp_1__a")]
    names = [t["function"]["name"] for t in tool_loop._native_tool_schemas(wired, allow_escalation=True)]
    assert names == ["attach_file", "mcp_1__a", "mcp_2__z", "recall", "web_search", "escalate"]
