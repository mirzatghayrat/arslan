"""0.1.59: an English request gets an English answer.

Seen 2026-10-09 while recording a promo on the English interface: an English request came back
in Chinese, and so did the background job's goal and checks and the lesson after it. The prompt
said "reply in the user's language" but carried whole Chinese sections, wrapped the user's own
message in Chinese labels, and never named the language. Now every turn names it, decided by
the user's latest message, and the fixed prompt has no Chinese in it at all.
"""
from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from arslan.llm.presets import provider_options
from server.db.models import Base
from server.orchestrator import arslan, tool_loop

CJK = re.compile(r"[぀-ヿ一-鿿가-힯　-〿＀-￯]")


@pytest.mark.parametrize("message, ui, expected", [
    ("In the background: copy this year's invoice PDFs from ~/ArslanDemo/Downloads into "
     "~/ArslanDemo/Invoices, then tell me which months are missing.", "zh", "English"),
    ("把下载文件夹里 10 月的发票整理成一张表", "en", "Chinese"),
    ("copy 发票.pdf to ~/Docs please, then tell me", "zh", "English"),      # a Chinese file name
    ("What does 你好 mean? Please explain it to me", "zh", "English"),      # a Chinese word, not a file
    ("帮我把 README.md 翻译成英文", "en", "Chinese"),                        # an English file name
    ("このファイルを開いて", "en", "Japanese"),
    ("Kannst du bitte die Datei öffnen und mir sagen, was drin ist", "en", "German"),
    ("~/Downloads/report.pdf", "fr", "French"),                               # no words: the interface
    ("~/Downloads/report.pdf", "zh", "Chinese"),
])
def test_the_latest_message_decides_the_language(message, ui, expected):
    assert arslan.reply_language(message, ui) == expected


def test_an_unsure_latin_message_is_never_answered_in_chinese():
    lang = arslan.reply_language("ok thx", "zh")
    assert "not Chinese" in lang


def test_the_fixed_prompt_has_no_chinese_in_it():
    # Chinese sections in the cached prefix pulled DeepSeek into Chinese on English requests.
    assert not CJK.search(arslan._ANSWER_STABLE_PREFIX)
    assert not CJK.search(arslan.BACKGROUND_SYSTEM)


def test_the_users_own_message_is_not_wrapped_in_chinese_labels():
    out = arslan.build_user_blocks("summarise it", "a long attached text", None)
    assert out == "[Attached material]\na long attached text\n\n[User message]\nsummarise it"


def test_provider_names_are_english():
    for option in provider_options():
        assert not CJK.search(option["label"]), option


def test_background_work_asks_for_the_goal_and_checks_in_the_users_language():
    props = tool_loop._NATIVE_PARAM_SCHEMAS["start_background_work"]["properties"]
    assert props["goal"]["description"] == "The work to do, in the user's own words and language."
    assert props["criteria"]["items"]["properties"]["description"]["description"] == "One check, in the user's language."


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    yield maker
    await engine.dispose()


def _capture_system(monkeypatch) -> list[str]:
    seen: list[str] = []

    async def fake_run_native(*, system, on_chunk, **kw):
        seen.append(str(system))
        on_chunk("ok")
        return {"final": "ok", "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", fake_run_native)
    return seen


@pytest.mark.parametrize("message, expected", [
    ("Copy this year's invoices and tell me which months are missing.", "English"),
    ("把今年的发票复制过去,告诉我缺哪几个月", "Chinese"),
])
async def test_a_chat_turn_names_its_reply_language(memdb, monkeypatch, message, expected):
    seen = _capture_system(monkeypatch)
    await arslan._handle_answer("c-lang", message, lambda e: None)
    assert f"Reply language for this turn: {expected}." in seen[0]


async def test_a_background_job_answers_in_the_language_the_user_asked_in(memdb, monkeypatch):
    # The goal can come out in the wrong language (that is the bug); the user's own message wins.
    seen = _capture_system(monkeypatch)

    async def fake_context(conversation_id):
        return {"summary": "", "history": [
            {"role": "user", "content": "In the background: copy this year's invoice PDFs, then tell me "
                                        "which months are missing."},
            {"role": "assistant", "content": "Started."}]}
    monkeypatch.setattr(arslan.memory, "assemble_working_context", fake_context)

    class Confirm:
        command = workspace_write = schedule = None
    await arslan.background_body("c-bg", "把今年的发票 PDF 复制过去", lambda e: None, Confirm())
    assert "Reply language for this turn: English." in seen[0]


async def test_saved_configs_lose_the_old_chinese_preset_names_but_not_a_name_the_user_typed():
    from server.db.migrations.versions._0066_provider_labels_english import upgrade_sync
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for label in ("OpenRouter (聚合，含 Claude/Gemini)", "通义千问 Qwen (阿里云)", "我的 OpenRouter"):
            await conn.execute(text("INSERT INTO provider_configs (label, provider, model, api_key, is_primary) "
                                    "VALUES (:l, 'openrouter', 'm', '', 0)"), {"l": label})
        await conn.run_sync(upgrade_sync)
        await conn.run_sync(upgrade_sync)                                   # idempotent
        labels = sorted((await conn.execute(text("SELECT label FROM provider_configs"))).scalars())
    await engine.dispose()
    assert labels == ["OpenRouter (Claude, Gemini and more)", "Qwen (Alibaba Cloud)", "我的 OpenRouter"]
