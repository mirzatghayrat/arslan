"""D6: a step whose arguments can't go into the task record is refused alone; secrets are screened on
the raw values, never on JSON-encoded text.

Field case (K3's Claude run, T2 r2): a background job's `edit_file` wrote a note ending in
"无验证码：**" and a URL on the next line. `json.dumps` writes the newline as a literal `\\n`, which is
not whitespace, so the encoded text matched the "验证码: <4+ non-space>" rule and the whole job stopped
(`job_blocked`) without the model being told why.
"""
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from arslan.companion.memory import MemoryActor, decide_write
from arslan.companion.memory import MemoryError as CompanionMemoryError
from server.db.models import CompanionTask
from server.services import host_run
from server.services.task_repository import TaskError, encoded_action, repository
from tests.server.test_style_references import write
from tests.server.test_task_repository import spec, started
from tests.server.test_task_service import run

# T2 r2's note, as the model wrote it (a placeholder URL).
T2_NOTE = "**重大进展……curl 直接可取，无需登录/无验证码：**\nhttps://example.test/api/items?page=1"
COOKIE = "Cookie: session=abcdef123456"
# A made-up value, joined at run time so the secret scanner never sees a key next to a value.
FAKE = "-".join(("fake", "value", "1234"))


def _edit(new):
    return {"path": "notes.md", "old": "a", "new": new}


def test_t2s_note_goes_into_the_task_record():
    assert "无验证码" in encoded_action("edit_file", _edit(T2_NOTE))


@pytest.mark.parametrize("arguments", [
    _edit(COOKIE),                                                 # a real cookie value
    _edit("验证码：\n12345678"),                                    # the rule itself is unchanged
    {"command": "x" * 262_145},                                    # over 256 KB encoded
])
def test_a_real_secret_or_an_oversized_step_is_still_refused(arguments):
    with pytest.raises(TaskError, match="^task_action_arguments_not_journalable$"):
        encoded_action("run_command", arguments)


# What the check on the encoded text used to catch as a side effect: in `"key":"value"` the rule ran
# across the key, so a key that contains a credential word was refused. The raw-value check now does
# that itself (②Main and ⓪Plan, Opus 5.5, on the D6 card).
@pytest.mark.parametrize("arguments", [
    {"config": {"db_password": FAKE}},                             # key: value, as raw text
    {"headers": {"x-api-key": FAKE}},
    {"env": {"GITHUB_ACCESS_TOKEN": FAKE}},
    {"data": {"Bearer abcdefghijklmnop1234": 1}},                  # the key is itself a secret
    {"data": {"Bearer abcdefghijklmnop1234": None}},               # … with nothing in it
    {"config": {"db_password": {"value": FAKE}}},                  # a credential-named key holding a structure
])
def test_a_credential_word_in_a_key_is_still_refused(arguments):
    with pytest.raises(TaskError, match="^task_action_arguments_not_journalable$"):
        encoded_action("write_file", arguments)


@pytest.mark.parametrize("arguments", [
    {"has_password": False},                                       # a boolean is not a secret
    {"db_password": {}},                                           # nothing in it
    {"notes": {"text": T2_NOTE}},                                  # a nested note: never dumped as JSON
])
def test_what_is_not_a_secret_goes_into_the_task_record(arguments):
    encoded_action("write_file", arguments)


async def test_an_unjournalable_step_is_refused_as_a_tool_result_and_the_turn_goes_on(execution_db, monkeypatch):
    """The task record's refusal used to propagate and stop the whole job (`job_blocked`). A secret
    never reaches it: the loop's own screen refuses that call first, on the same raw values."""
    from server.orchestrator import tool_loop

    class Executor:
        calls = 0

        async def execute(self, args):
            Executor.calls += 1
            return {"ok": True}

    async def resolve(key):
        return Executor()

    async def tools():
        return [{"key": "edit_file", "description": "edit"}]
    monkeypatch.setattr(tool_loop, "resolve_executor", resolve)
    results = []

    async def function(conversation, message, emit):
        async def body(sink):
            for new in ("x" * 262_145, COOKIE, "plain text"):
                results.append(await tool_loop._dispatch_tool(
                    "edit_file", _edit(new), "", resolve_tools=tools, emit=emit,
                    tool_timeout_s=2, tool_trace=[], convo=[], conversation_id=conversation))
            return "Answer delivered"
        return await host_run.execute(conversation, message, emit, body)
    assert await run(function) == "Answer delivered", "the task goes on after the refused steps"
    too_long, secret, after = results
    assert too_long["ok"] is False and too_long["code"] == "task_action_arguments_not_journalable"
    assert too_long["error"].startswith("This step did not run") and "environment variable" in too_long["error"]
    assert secret["ok"] is False and secret["code"] == "credentials_not_tool_data"
    assert COOKIE not in str(secret)
    assert Executor.calls == 1 and after["ok"] is True, "only the refused steps are skipped"
    async with execution_db() as db:
        task = (await db.execute(select(CompanionTask))).scalar_one()
    assert task.phase == "succeeded", "not job_blocked"


# The same screening on JSON-encoded text sat in three more places (the D6 card, item 3).

def test_a_project_summary_with_t2s_note_is_accepted_and_a_secret_is_not():
    from server.api.companion import ProjectInput
    assert ProjectInput(name="x", summary=T2_NOTE).summary == T2_NOTE
    with pytest.raises(ValidationError, match="credentials_not_project_metadata"):
        ProjectInput(name="x", summary=COOKIE)


async def test_a_task_spec_with_t2s_note_is_created_and_a_secret_is_not(execution_db):
    async with repository() as repo:
        assert (await repo.create(spec(instruction=T2_NOTE), "conversation"))["version"]
        with pytest.raises(TaskError, match="^credentials_not_task_data$"):
            await repo.create(spec("task-two", instruction=COOKIE), "conversation")


async def test_a_revised_task_spec_with_t2s_note_is_kept_and_a_secret_is_not(execution_db):
    initial = await started()
    async with repository() as repo:
        failed = await repo.finish("task-one", initial["state"]["run_id"], phase="failed")
        with pytest.raises(TaskError, match="^task_revision_not_persistable$"):
            await repo.revise("task-one", failed["version"], spec(revision=2, instruction=COOKIE))
        revised = await repo.revise("task-one", failed["version"], spec(revision=2, instruction=T2_NOTE))
    assert revised["state"]["phase"] == "waiting_user"


def _with_rationale(rationale):
    base = write()
    return base.model_copy(update={"style_reference": base.style_reference.model_copy(update={"rationale": rationale})})


def test_a_style_reference_with_t2s_note_is_kept_and_a_secret_is_not():
    assert decide_write(_with_rationale(T2_NOTE), MemoryActor(origin="user"))
    with pytest.raises(CompanionMemoryError, match="credentials_not_memory"):
        decide_write(_with_rationale(COOKIE), MemoryActor(origin="user"))
