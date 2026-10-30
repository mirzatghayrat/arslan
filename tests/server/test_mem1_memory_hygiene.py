"""MEM1 (v0.1.64, card docs/plans/0164/INB-inbox-progress.md "MEM1"; memory plan item A, docs/plans/0162/README.md
§8): memory write hygiene.

1. Merge by meaning: before Arslan stores a new entry, the nearest live entries of the same kind and scope are
   asked about (the judge's `memory.merge`, as lessons do). The same meaning updates the older entry instead of
   adding a row: its id stays, its date is refreshed, the stricter sensitivity is kept, and the new write's source
   is added (#475 H1/J2). No answer from the judge means no merge.
2. ②Main's review points: a candidate that would wait (INB2: not present, or a conversation off the list) never
   refreshes an active entry; it waits as a proposal against it.
3. Language and gender, and no one-off task state, in what the extractor keeps (turn_facts).
"""
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
    judge.answers["memory.merge"] = _same_as_first
    first = await _write(tool, FIRST)
    [before] = await _entries(memory)
    out = await _write(tool, SAME)
    [after] = await _entries(memory)                                         # still one row
    assert after.id == first["id"] and out["id"] == first["id"]               # the older id
    assert after.updated_at > before.updated_at                              # the date refreshed
    assert after.status == "active"


async def test_a_close_but_different_entry_is_its_own_row(memory, judge):  # noqa: F811
    judge.answers["memory.merge"] = _same_as_first
    await _write("remember", FIRST)
    await _write("remember", CLOSE)
    assert [e.status for e in await _entries(memory)] == ["active", "active"]


async def test_entries_that_share_only_the_user_are_never_asked_about(memory, judge):  # noqa: F811
    asked = []
    judge.answers["memory.merge"] = lambda state: asked.append(state) or False
    await _write("remember", FIRST)
    await _write("remember", "The user lives in Berlin")                    # only "the user" in common
    await _write("remember", "用户养了一只猫")
    await _write("remember", "用户住在柏林")                                  # only "用户" in common
    assert asked == []                                                       # no model call spent on them


async def test_no_answer_from_the_judge_is_no_merge(memory, judge):  # noqa: F811
    judge.answers["memory.merge"] = None                                     # off, the daily cap, no model
    await _write("remember", FIRST)
    await _write("remember", SAME)
    assert len(await _entries(memory)) == 2


async def test_a_merge_is_not_announced_as_a_new_memory(memory, judge):  # noqa: F811
    judge.answers["memory.merge"] = _same_as_first
    await _write("remember", FIRST)
    memory.frames.clear()
    await _write("remember", SAME)
    # "remembered … [Undo]" under the reply would delete the older entry.
    assert memory.frames == []


async def test_what_the_user_turned_off_stays_off(memory, judge):  # noqa: F811
    judge.answers["memory.merge"] = _same_as_first
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
    judge.answers["memory.merge"] = _same_as_first
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
    judge.answers["memory.merge"] = _same_as_first
    await _write("remember", FIRST)
    await _write("remember", SAME, outside=True)
    await _write("remember", SAME, present=False)
    [entry] = await _entries(memory)
    assert len(await _proposals(memory, entry.id)) == 1


async def test_the_merged_entry_carries_the_new_writes_source(memory, judge):  # noqa: F811
    judge.answers["memory.merge"] = _same_as_first
    await _write("remember", FIRST)
    run_id = await _run(memory, read_outside=False)
    await _write("remember", SAME, ctx=_ctx(run_id))
    [entry] = await _entries(memory)
    runs = {source.source_ref.get("run_id") for source in await _sources(memory, entry.id)
            if source.revision_id == entry.current_revision_id}
    assert run_id in runs                                                   # from_off_the_list traces it too


async def test_the_stricter_sensitivity_is_kept(memory, judge):  # noqa: F811
    judge.answers["memory.merge"] = _same_as_first
    await _write("remember", FIRST, present=False)                           # waits: not present
    await _write("remember", SAME, present=False, entry={"sensitive": True})
    [entry] = await _entries(memory)
    assert entry.sensitivity == "sensitive" and entry.status == "proposed"


async def test_the_extractor_merges_too(memory, judge):  # noqa: F811
    judge.answers["memory.merge"] = _same_as_first
    with pc.bind(_ctx()):
        await memory_compat.save_facts([{"content": FIRST}])
        again = await memory_compat.save_facts([{"content": SAME}])
    assert again == [] and len(await _entries(memory)) == 1                   # merged, and not announced


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
    judge.answers["memory.merge"] = _same_as_first
    await _write("remember", FIRST, ctx=_ctx(cloud_memory_default=True))
    assert (await _entries(memory))[0].use_policy == "cloud_allowed"         # positive control
    await _write("remember", SAME)                                           # cloud memory off now
    [entry] = await _entries(memory)
    assert entry.use_policy == "local_only"
