"""MEM1 (v0.1.64, card docs/plans/0164/INB-inbox-progress.md "MEM1"; memory plan item A, docs/plans/0162/README.md
§8): memory write hygiene.

1. Merge by meaning: before Arslan stores a new entry, the nearest live entries of the same kind and scope are
   asked about (the judge's `memory.same`: the same thing, adding nothing). The same meaning updates the older entry
   instead of adding a row: its id stays, its date is refreshed, the stricter sensitivity is kept, and the new
   write's source is added (#475 H1/J2). No answer from the judge means no merge.
2. ②Main's review points: a candidate that would wait (INB2: not present, or a conversation off the list) never
   refreshes an active entry; it waits as a proposal against it. And from the review of #559: the judge sees only
   what a prompt could (H1), the ledger keeps no memory text, an explicit request is never merged (M1), the history
   shows a merge (M2), the judge has its own share of the cap (L1), a proposal a merge makes is announced (L2).
3. Language and gender, and no one-off task state, in what the extractor keeps (turn_facts).
"""
import dataclasses

import pytest
from sqlalchemy import select

from server.db.companion_models import MemoryEntry, MemorySource
from server.db.models import MemoryProposal
from server.services import memory_compat, turn_facts
from server.services import personal_context as pc
from tests.server.test_inb2_about_you_direct import _ctx, _run, _write, memory  # noqa: F401  (the fixture)
from tests.server.test_s64_0_outside_content_gaps import judge  # noqa: F401  (the fixture)

FIRST = "The user prefers short answers"
SAME = "The user likes brief replies"                      # the same meaning, other words
CLOSE = "The user prefers short meetings"                  # close, but a different thing


def _same_as_first(state) -> bool:
    """The fake judge: only the pair FIRST / SAME says the same thing."""
    return {state["candidate"], state["existing"]} == {FIRST, SAME}


async def _entries(db):
    async with db() as session:
        return (await session.scalars(select(MemoryEntry).where(MemoryEntry.kind == "preference")
                                      .order_by(MemoryEntry.created_at))).all()


async def _sources(db, entry_id):
    async with db() as session:
        return (await session.scalars(select(MemorySource).where(MemorySource.entry_id == entry_id))).all()


async def _proposals(db, entry_id):
    async with db() as session:
        return (await session.scalars(select(MemoryProposal).where(
            MemoryProposal.target_entry_id == entry_id))).all()


# -- 1. merge by meaning ------------------------------------------------------------------------------

@pytest.mark.parametrize("tool", ["remember", "memory_note"])
async def test_the_same_meaning_updates_the_older_entry_instead_of_adding_one(memory, judge, tool):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    first = await _write(tool, FIRST)
    [before] = await _entries(memory)
    out = await _write(tool, SAME)
    [after] = await _entries(memory)                                         # still one row
    assert after.id == first["id"] and out["id"] == first["id"]               # the older id
    assert after.updated_at > before.updated_at                              # the date refreshed
    assert after.status == "active"


async def test_a_close_but_different_entry_is_its_own_row(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    await _write("remember", FIRST)
    await _write("remember", CLOSE)
    assert [e.status for e in await _entries(memory)] == ["active", "active"]


async def test_entries_that_share_only_the_user_are_never_asked_about(memory, judge):  # noqa: F811
    asked = []
    judge.answers["memory.same"] = lambda state: asked.append(state) or False
    await _write("remember", FIRST)
    await _write("remember", "The user lives in Berlin")                    # only "the user" in common
    await _write("remember", "用户养了一只猫")
    await _write("remember", "用户住在柏林")                                  # only "用户" in common
    assert asked == []                                                       # no model call spent on them


async def test_no_answer_from_the_judge_is_no_merge(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = None                                     # off, the daily cap, no model
    await _write("remember", FIRST)
    await _write("remember", SAME)
    assert len(await _entries(memory)) == 2


async def test_a_merge_is_not_announced_as_a_new_memory(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    await _write("remember", FIRST)
    memory.frames.clear()
    await _write("remember", SAME)
    # "remembered … [Undo]" under the reply would delete the older entry.
    assert memory.frames == []


async def test_what_the_user_turned_off_stays_off(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    await _write("remember", FIRST)
    async with memory() as session:
        entry = (await session.scalars(select(MemoryEntry))).one()
        entry.status = "paused"                                              # the user said no
        await session.commit()
    await _write("remember", SAME)
    [entry] = await _entries(memory)
    assert entry.status == "paused" and len(await _sources(memory, entry.id)) == 1


# -- 2. ②Main's points: INB2, provenance, sensitivity ---------------------------------------------------

async def test_a_candidate_that_would_wait_never_refreshes_an_active_entry(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    await _write("remember", FIRST)
    [before] = await _entries(memory)
    out = await _write("remember", SAME, outside=True)                       # this turn read a page
    [after] = await _entries(memory)
    assert (after.version, after.current_revision_id, after.updated_at, after.sensitivity) == (
        before.version, before.current_revision_id, before.updated_at, before.sensitivity)
    assert len(await _sources(memory, after.id)) == 1                         # nothing of the page's turn added
    [proposal] = await _proposals(memory, after.id)                          # it waits, against the entry
    assert out["status"] == "proposed" and proposal.reason == "external_seen" and proposal.status == "pending"


async def test_the_same_waiting_candidate_again_joins_its_proposal(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    await _write("remember", FIRST)
    await _write("remember", SAME, outside=True)
    await _write("remember", SAME, present=False)
    [entry] = await _entries(memory)
    assert len(await _proposals(memory, entry.id)) == 1


async def test_the_merged_entry_carries_the_new_writes_source(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    await _write("remember", FIRST)
    run_id = await _run(memory, read_outside=False)
    await _write("remember", SAME, ctx=_ctx(run_id))
    [entry] = await _entries(memory)
    runs = {source.source_ref.get("run_id") for source in await _sources(memory, entry.id)
            if source.revision_id == entry.current_revision_id}
    assert run_id in runs                                                   # from_off_the_list traces it too


async def test_the_stricter_sensitivity_is_kept(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    ctx = _ctx(allow_sensitive=True)                                          # this context may show sensitive
    await _write("remember", FIRST, present=False, ctx=ctx)                  # waits: not present
    await _write("remember", SAME, present=False, entry={"sensitive": True}, ctx=ctx)
    [entry] = await _entries(memory)
    assert entry.sensitivity == "sensitive" and entry.status == "proposed"


async def test_the_extractor_merges_too(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    with pc.bind(_ctx()):
        await memory_compat.save_facts([{"content": FIRST}])
        again = await memory_compat.save_facts([{"content": SAME}])
    [entry] = await _entries(memory)                                         # merged into the waiting one
    # It joined that entry's proposal, so the chat line names it (②Main's review of #559, L2).
    assert [(fact.entry_id, fact.status, fact.content) for fact in again] == [(entry.id, "proposed", SAME)]
    assert again[0].proposal_id is not None


# -- 3. what the extractor keeps ---------------------------------------------------------------------

def _reply(*facts: str) -> str:
    import json
    return json.dumps({"new_facts": [{"content": fact, "sensitive": False} for fact in facts], "practices": []})


def test_the_prompt_asks_for_the_users_language_and_never_a_gender():
    assert "same language as the user's own messages" in turn_facts._SYSTEM
    assert "never guess the user's gender" in turn_facts._SYSTEM
    assert "the user" in turn_facts._SYSTEM


def test_a_fact_that_guesses_the_users_gender_is_not_kept():
    kept = turn_facts.parse(_reply("He prefers short answers", "The user prefers short answers",
                                   "She writes in British English", "用户喜欢简短的回答"))
    assert [f["content"] for f in kept] == ["The user prefers short answers", "用户喜欢简短的回答"]


@pytest.mark.parametrize("state", [
    "The user's project lives in ~/code/shop",
    "The user keeps the build in /Users/someone/build/out",
    "The user's server runs on localhost:8080",
    "The user's app listens on port 5173",
    "The user is currently deploying the shop to staging",
    "用户正在部署商店服务",
], ids=["home-path", "absolute-path", "localhost-port", "port", "currently", "currently-zh"])
def test_one_off_task_state_is_not_kept(state):
    kept = turn_facts.parse(_reply(state, "The user prefers short answers"))
    assert [f["content"] for f in kept] == ["The user prefers short answers"]   # the durable one stays


def test_the_prompt_keeps_task_state_out():
    assert "file paths" in turn_facts._SYSTEM and "ports" in turn_facts._SYSTEM
    assert "currently doing" in turn_facts._SYSTEM


async def test_the_narrower_use_is_kept(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    await _write("remember", FIRST, ctx=_ctx(cloud_memory_default=True))
    assert (await _entries(memory))[0].use_policy == "cloud_allowed"         # positive control
    await _write("remember", SAME)                                           # cloud memory off now
    [entry] = await _entries(memory)
    assert entry.use_policy == "local_only"



# -- ②Main's review of #559 -----------------------------------------------------------------------------

def _recorder(fake):
    asked = []

    def answer(state):
        asked.append(state)
        return _same_as_first(state)
    fake.answers["memory.same"] = answer
    return asked


async def test_a_local_only_entry_is_never_sent_to_a_cloud_judge(memory, judge):  # noqa: F811
    asked = _recorder(judge)
    await _write("remember", FIRST)                                          # cloud memory off: local_only
    cloud = dataclasses.replace(_ctx(), model_is_local=False, cloud_memory_default=True)
    await _write("remember", SAME, ctx=cloud)
    assert asked == [] and len(await _entries(memory)) == 2
    await _write("remember", SAME, ctx=_ctx())                               # positive control: a local judge
    assert any(state["existing"] == FIRST for state in asked)


async def test_a_sensitive_entry_is_sent_only_where_a_prompt_could_show_it(memory, judge):  # noqa: F811
    asked = _recorder(judge)
    await _write("remember", FIRST, present=False, entry={"sensitive": True}, ctx=_ctx(allow_sensitive=True))
    await _write("remember", SAME, present=False)                            # allow_sensitive off
    assert asked == []
    await _write("remember", SAME, present=False, ctx=_ctx(allow_sensitive=True))
    assert any(state["existing"] == FIRST for state in asked)                # positive control


@pytest.mark.parametrize("ctx", [
    {"no_memory": True},
    {"model_is_local": False, "cloud_memory_default": False},
], ids=["memory-off", "cloud-model-without-cloud-memory"])
async def test_no_judge_call_where_no_memory_may_be_shown(memory, judge, ctx):  # noqa: F811
    asked = _recorder(judge)
    await _write("remember", FIRST)
    await _write("remember", SAME, ctx=dataclasses.replace(_ctx(), **ctx))
    assert asked == []


async def test_the_judgments_ledger_keeps_no_memory_text(memory, monkeypatch):  # noqa: F811
    import json

    from arslan.models import LLMResponse
    from server.db.models import Judgment
    from server.services import judgment

    class Model:
        model = "fake-judge"

        async def chat(self, system, user, **kwargs):
            return LLMResponse(content=json.dumps({"answer": True, "p": 0.99}), usage={})

    async def adapter():
        return Model()
    monkeypatch.setattr(judgment, "_adapter", adapter)
    first = await _write("remember", FIRST)
    await _write("remember", SAME)
    async with memory() as session:
        [row] = (await session.scalars(select(Judgment).where(Judgment.point == "memory.same"))).all()
    kept = json.dumps(row.state)
    assert row.verdict is True and len(await _entries(memory)) == 1         # it did merge
    assert "short" not in kept and "brief" not in kept                       # neither text
    assert row.ref == f"memory:{first['id']}"                                # which entry, by id
    assert all(value.startswith("sha256:") for value in row.state.values())


async def test_the_judges_own_share_is_not_the_shared_cap(memory, monkeypatch):  # noqa: F811
    import json

    from arslan.models import LLMResponse
    from server.services import judgment

    class Model:
        model = "fake-judge"

        async def chat(self, system, user, **kwargs):
            return LLMResponse(content=json.dumps({"answer": True, "p": 0.99}), usage={})

    async def adapter():
        return Model()

    async def spent(db, budget="judgment"):
        return judgment.DAILY_TOKEN_CAP if budget == "judgment" else 0       # every other point is capped
    monkeypatch.setattr(judgment, "_adapter", adapter)
    monkeypatch.setattr(judgment, "_tokens_today", spent)
    await _write("remember", FIRST)
    await _write("remember", SAME)
    assert len(await _entries(memory)) == 1                                  # memory.same still answered
    assert judgment.REGISTRY["memory.same"].budget != "judgment"


async def test_an_explicit_request_to_remember_is_never_merged(memory, judge):  # noqa: F811
    import hashlib

    from arslan.companion.content_policy import normalized_memory
    asked = _recorder(judge)
    await _write("remember", FIRST)
    digest = hashlib.sha256(normalized_memory(SAME).encode()).hexdigest()
    explicit = _ctx(explicit_save_ref="message:9", explicit_save_digest=digest, allow_global_save=True)
    out = await _write("remember", SAME, ctx=explicit)
    assert asked == [] and len(await _entries(memory)) == 2 and out["confirmation_kind"] == "explicit_user_request"


async def test_merge_into_itself_refuses_an_explicit_request(memory):  # noqa: F811
    import hashlib

    from arslan.companion.content_policy import normalized_memory
    from arslan.companion.memory import MemoryScope, MemoryWrite
    from server.services.memory_repository import repository
    first = await _write("remember", FIRST)
    digest = hashlib.sha256(normalized_memory(SAME).encode()).hexdigest()
    actor = _ctx(explicit_save_ref="message:9", explicit_save_digest=digest, allow_global_save=True).actor("host")
    async with repository() as repo:
        merged = await repo.merge_into(first["id"], first["version"], MemoryWrite(
            content=SAME, scope=MemoryScope(kind="global")), actor)
    assert merged is None                                                    # the caller stores it as its own


async def test_the_history_shows_the_merge_and_what_it_changed(memory, judge):  # noqa: F811
    from server.services.memory_repository import repository
    judge.answers["memory.same"] = _same_as_first
    first = await _write("remember", FIRST, ctx=_ctx(cloud_memory_default=True))   # cloud_allowed
    await _write("remember", SAME)                                           # cloud memory off now: local_only
    async with repository() as repo:
        rows = await repo.history(first["id"])
    assert [row["change_reason"] for row in rows] == ["merged", "created"]
    assert rows[0]["merged"] == {"conversation_id": "c-inb2", "use_policy": "local_only"}
    assert rows[0]["version"] == rows[1]["version"] == 1                     # no new version: proposals still hold


async def test_a_proposal_a_merge_makes_is_announced(memory, judge):  # noqa: F811
    judge.answers["memory.same"] = _same_as_first
    await _write("remember", FIRST)
    memory.frames.clear()
    out = await _write("remember", SAME, outside=True)
    assert [(f["type"], f["proposal_id"], f["content"]) for f in memory.frames] == [
        ("memory_proposed", out["proposal_id"], SAME)]


def test_a_pronoun_about_someone_else_is_kept():
    kept = turn_facts.parse(_reply("The user's sister is a doctor; she lives in Lyon", "He prefers tea"))
    assert [f["content"] for f in kept] == ["The user's sister is a doctor; she lives in Lyon"]


async def test_a_sensitive_candidate_is_not_sent_where_a_prompt_could_not_show_it(memory, judge):  # noqa: F811
    asked = _recorder(judge)
    await _write("remember", FIRST)                                          # an ordinary entry
    await _write("remember", SAME, entry={"sensitive": True})                # allow_sensitive off
    await _write("remember", "The user's family likes brief replies")        # sensitive by its words ("family")
    assert asked == []
    await _write("remember", SAME, entry={"sensitive": True}, ctx=_ctx(allow_sensitive=True))
    assert any(state["existing"] == FIRST for state in asked)                # positive control


async def test_deleting_the_entry_deletes_the_judgments_about_it(memory, judge):  # noqa: F811
    from server.db.models import Judgment
    from arslan.companion.memory import MemoryActor
    from server.services.memory_repository import repository
    first = await _write("remember", FIRST)
    async with memory() as session:
        session.add_all([Judgment(point="memory.same", mode="active", state={}, state_hash="h", ref=f"memory:{first['id']}"),
                         Judgment(point="memory.same", mode="active", state={}, state_hash="h", ref="memory:another")])
        await session.commit()
    async with repository() as repo:
        entry = await repo.get(first["id"])
        await repo.delete_entry(entry.id, entry.version, MemoryActor(origin="user"))
    async with memory() as session:
        assert (await session.scalars(select(Judgment.ref))).all() == ["memory:another"]


async def test_undoing_the_turn_that_taught_it_deletes_the_judgments_about_it(memory, judge):  # noqa: F811
    from server.db.models import Judgment
    from server.services.memory_repository import repository
    run_id = await _run(memory, read_outside=False)
    first = await _write("remember", FIRST, ctx=_ctx(run_id))
    async with memory() as session:
        session.add(Judgment(point="memory.same", mode="active", state={}, state_hash="h", ref=f"memory:{first['id']}"))
        await session.commit()
    async with repository() as repo:
        assert await repo.forget_turns("c-inb2", set(), {run_id}) == 1          # the entry went with its turn
    async with memory() as session:
        assert (await session.scalars(select(Judgment.ref))).all() == []
