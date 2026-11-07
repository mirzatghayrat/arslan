"""What the user asks Arslan to remember, in their own words, reaches a cloud model when "Remember me" or the conversation's
switch allows and the setup isn't all local models. Everything that holds memory back stays. These run real turns:
the real tool loop and tools, `task_context.load`, the prompt the model is handed and the post-turn job. Written by hand:
the turn model's replies, and the extractor's and the judge's."""
import asyncio
import hashlib
import json

import pytest
from sqlalchemy import select

from server.db.companion_models import ConversationContext, MemoryEntry, MemoryRevision
from server.db.models import Setting
from server.orchestrator import arslan, tool_loop
from server.services import judgment, lessons, memory_merge, turn_facts
from server.services import personal_context as pc
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository
from tests.server.test_arslan_loop import _LLMResp, _tc, settle_after_turn

from arslan.companion.content_policy import normalized_memory
from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite, decide_write

CID = "c-remember"
WORDS = "I want worked examples in every answer"
ASK = f"Remember that {WORDS}"
LATER = "Do you know how I like worked examples in an answer?"
ELSEWHERE = "c-another-conversation"       # its history doesn't hold the user's words, so only memory can bring them


class _Model:
    """The turn's model: it makes the tool call it's given once, and keeps every prompt it was handed."""

    def __init__(self, tool=None, args=None):
        self.call, self.prompts = (_tc(tool, args) if tool else None), []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.prompts.append(f"{system}\n{user}\n{json.dumps(history, default=str)}")
        call, self.call = self.call, None
        return _LLMResp(content="", tool_calls=[call]) if call else _LLMResp(content="Done.")


class _Extractor:
    def __init__(self, facts):
        self.facts = facts

    async def chat(self, *, system, user):
        return _LLMResp(content=json.dumps({"new_facts": [{"content": f, "sensitive": False} for f in self.facts],
                                            "practices": []}))


class _Judge:
    async def chat(self, *, system, user):
        return _LLMResp(content=json.dumps({"answer": True, "p": 0.95}))


@pytest.fixture
async def memory(execution_db, monkeypatch):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)

    async def no_match(content, **kwargs):
        return None
    monkeypatch.setattr(memory_merge, "same_meaning", no_match)
    _extracts(monkeypatch, [])

    async def judge():
        return _Judge()
    monkeypatch.setattr(judgment, "_adapter", judge)
    return execution_db


def _extracts(monkeypatch, facts):
    async def extractor():
        return _Extractor(facts)
    monkeypatch.setattr(turn_facts, "_get_adapter", extractor)


def _remember(content=WORDS, **args):
    return "remember", {"kind": "preference", "action": "append", "content": content, **args}


async def _turn(monkeypatch, message, tool=None, args=None, cid=CID):
    model = _Model(tool, args)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    await arslan.handle_user_message(cid, message, lambda event: None)
    await settle_after_turn()
    await asyncio.gather(*list(lessons._background))
    return "\n".join(model.prompts)


async def _next_prompt(monkeypatch, message=LATER):
    return await _turn(monkeypatch, message, cid=ELSEWHERE)


async def _stored(db):
    async with db() as session:
        rows = (await session.execute(select(MemoryEntry, MemoryRevision).join(
            MemoryRevision, MemoryRevision.id == MemoryEntry.current_revision_id))).all()
    return {revision.content: entry for entry, revision in rows}


async def _set_up(db, *rows):
    async with db() as session:
        session.add_all(rows)
        await session.commit()


# -- the save reaches a cloud model ---------------------------------------------------------------------------------

async def test_the_users_own_words_reach_the_cloud_models_next_prompt(memory, monkeypatch):
    """The default setup, as a turn loads it: a provider not known to be local, and "Remember me" on."""
    await _turn(monkeypatch, ASK, *_remember())
    entry = (await _stored(memory))[WORDS]
    assert (entry.status, entry.confirmation_kind, entry.use_policy) == ("active", "explicit_user_request", "cloud_allowed")
    assert WORDS in await _next_prompt(monkeypatch)


async def test_the_same_for_memory_note(memory, monkeypatch):
    await _turn(monkeypatch, ASK, "memory_note", {"action": "add", "set": "about_you", "text": WORDS})
    entry = (await _stored(memory))[WORDS]
    assert (entry.confirmation_kind, entry.use_policy) == ("explicit_user_request", "cloud_allowed")
    assert WORDS in await _next_prompt(monkeypatch, "What is 2 + 2?")     # always in view, no matching words needed


async def test_the_conversations_own_switch_allows_it_with_remember_me_off(memory, monkeypatch):
    await _set_up(memory, Setting(key="memory_in_conversations", value="false"),
                  ConversationContext(id=CID, cloud_memory_allowed=True),
                  ConversationContext(id=ELSEWHERE, cloud_memory_allowed=True))
    await _turn(monkeypatch, ASK, *_remember())
    assert (await _stored(memory))[WORDS].use_policy == "cloud_allowed"
    assert WORDS in await _next_prompt(monkeypatch)


# -- what holds it back still does ----------------------------------------------------------------------------------

async def test_with_remember_me_off_it_stays_on_this_mac(memory, monkeypatch):
    await _set_up(memory, Setting(key="memory_in_conversations", value="false"))
    await _turn(monkeypatch, ASK, *_remember())
    entry = (await _stored(memory))[WORDS]
    assert (entry.status, entry.confirmation_kind, entry.use_policy) == ("active", "explicit_user_request", "local_only")
    assert WORDS not in await _next_prompt(monkeypatch)


SENSITIVE = "I have a medical appointment about worked examples"


@pytest.mark.parametrize("content, flag", [(SENSITIVE, {}), (WORDS, {"sensitive": True})], ids=["keyword", "flagged"])
async def test_a_sensitive_save_waits_and_stays_on_this_mac(memory, monkeypatch, content, flag):
    await _turn(monkeypatch, f"Remember that {content}", *_remember(content, **flag))
    entry = (await _stored(memory))[content]
    assert (entry.status, entry.sensitivity, entry.use_policy) == ("proposed", "sensitive", "local_only")
    assert entry.confirmation_kind is None
    assert content not in await _next_prompt(monkeypatch)


async def test_words_the_user_didnt_say_arent_their_request(memory, monkeypatch):
    other = "I want long answers with worked examples"
    await _turn(monkeypatch, ASK, *_remember(other))
    assert (await _stored(memory))[other].confirmation_kind != "explicit_user_request"


async def test_a_key_is_refused(memory, monkeypatch):
    """From an ordinary message: a turn whose message holds a key is refused before any tool runs."""
    key = "my key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
    await _turn(monkeypatch, "Note down my key", *_remember(key))
    assert await _stored(memory) == {}


async def test_a_conversation_that_learns_nothing_stores_nothing(memory, monkeypatch):
    await _set_up(memory, ConversationContext(id=CID, no_learning=True))
    await _turn(monkeypatch, ASK, *_remember())
    assert await _stored(memory) == {}


async def test_a_worker_cant_use_the_users_request(memory):
    write = MemoryWrite(content=WORDS, scope=MemoryScope(kind="global"))
    decision = decide_write(write, MemoryActor(origin="worker", explicit_save_ref="message:1", cloud_memory_allowed=True,
                                               explicit_save_digest="anything", allow_global_save=True))
    assert (decision.status, decision.use_policy) == ("proposed", "local_only")


@pytest.mark.parametrize("switches, use", [
    ({"model_is_local": False, "cloud_memory_default": True}, "cloud_allowed"),
    ({"model_is_local": False, "cloud_memory_allowed": True}, "cloud_allowed"),
    ({"model_is_local": False}, "local_only"),
    ({"model_is_local": True, "cloud_memory_default": True}, "local_only"),
    ({"model_is_local": True, "cloud_memory_allowed": True}, "local_only"),
], ids=["remember-me", "this-conversation", "no-setting", "local-remember-me", "local-this-conversation"])
def test_a_save_is_for_the_cloud_only_with_a_cloud_model_and_a_setting_allowing_it(switches, use):
    """A save on a local setup stays on this Mac, even if the user switches provider later:
    test_memory_multiturn_runtime's test_local_only_memory_is_filtered_from_cloud_prompt runs that through real turns."""
    digest = hashlib.sha256(normalized_memory(WORDS).encode()).hexdigest()
    ctx = pc.TaskMemoryContext(task_id="t", run_id="r", explicit_save_ref="message:1", explicit_save_digest=digest,
                               allow_global_save=True, **switches)
    decision = decide_write(MemoryWrite(content=WORDS, scope=MemoryScope(kind="global")), ctx.actor("host"))
    assert (decision.confirmation_kind, decision.use_policy) == ("explicit_user_request", use)


@pytest.mark.parametrize("use", ["local_only", "cloud_allowed"])
def test_the_users_own_form_still_decides_for_itself(use):
    write = MemoryWrite(content=WORDS, scope=MemoryScope(kind="global"), use_policy=use)
    assert decide_write(write, MemoryActor(origin="user", cloud_memory_allowed=True)).use_policy == use


async def test_saying_it_again_doesnt_widen_what_the_user_kept_on_this_mac(memory, monkeypatch):
    async with repository() as repo:
        mine = await repo.create(MemoryWrite(content=WORDS, scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    assert mine["use_policy"] == "local_only"
    await _turn(monkeypatch, ASK, *_remember())
    entry = (await _stored(memory))[WORDS]
    assert (entry.id, entry.use_policy, entry.confirmation_kind) == (mine["id"], "local_only", "user_form")
    assert WORDS not in await _next_prompt(monkeypatch)


# -- the post-turn job on the same turn -----------------------------------------------------------------------------

async def test_the_job_noticing_the_same_words_leaves_one_entry_for_the_cloud(memory, monkeypatch):
    _extracts(monkeypatch, [WORDS])
    await _turn(monkeypatch, ASK, *_remember())
    stored = await _stored(memory)
    assert set(stored) == {WORDS}
    assert (stored[WORDS].confirmation_kind, stored[WORDS].use_policy) == ("explicit_user_request", "cloud_allowed")
    _extracts(monkeypatch, [])
    assert WORDS in await _next_prompt(monkeypatch)


async def test_the_job_noticing_other_words_doesnt_touch_the_save(memory, monkeypatch):
    other = "Prefers tabs over spaces in worked examples"
    _extracts(monkeypatch, [other])
    await _turn(monkeypatch, ASK, *_remember())
    stored = await _stored(memory)
    assert (stored[WORDS].confirmation_kind, stored[WORDS].use_policy) == ("explicit_user_request", "cloud_allowed")
    assert (stored[other].confirmation_kind, stored[other].use_policy) == ("auto_noticed", "cloud_allowed")


async def test_the_job_noticing_a_sensitive_save_doesnt_bring_it_into_effect(memory, monkeypatch):
    _extracts(monkeypatch, [SENSITIVE])
    await _turn(monkeypatch, f"Remember that {SENSITIVE}", *_remember(SENSITIVE))
    entry = (await _stored(memory))[SENSITIVE]
    assert (entry.status, entry.sensitivity, entry.use_policy) == ("proposed", "sensitive", "local_only")
    _extracts(monkeypatch, [])
    assert SENSITIVE not in await _next_prompt(monkeypatch)


async def test_with_remember_me_off_the_job_doesnt_widen_it(memory, monkeypatch):
    await _set_up(memory, Setting(key="memory_in_conversations", value="false"))
    _extracts(monkeypatch, [WORDS])
    await _turn(monkeypatch, ASK, *_remember())
    stored = await _stored(memory)
    assert set(stored) == {WORDS} and stored[WORDS].use_policy == "local_only"
