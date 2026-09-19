"""Synthetic multi-turn bindings: real task, tool, memory and prompt boundaries.

The scripted adapter supplies tool intent and captures outbound prompts. It does
not prove natural-language interpretation or the quality of a real model answer.
"""
import json
from pathlib import Path
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select, update

from arslan.models import LLMResponse
from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.db.models import ArslanMessage, CompanionTask, ContextReceiptRecord, ConversationContext, Project, ProviderConfig, Run
from server.orchestrator import arslan, memory, tool_loop
from server.registry.memory_executors import RememberExecutor
from server.services import knowledge, personal_context, task_context
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository

SCENARIOS = {item["id"]: item for item in json.loads((
    Path(__file__).resolve().parents[2] / "evals/companion/memory-scenarios.json"
).read_text())["scenarios"]}


@pytest.fixture
async def runtime(execution_db, monkeypatch):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    async with execution_db() as db:
        await db.execute(insert(ProviderConfig).values(
            label="Synthetic local adapter", provider="ollama", model="fixture",
            base_url="http://127.0.0.1:11434/v1", api_key="", is_primary=True,
        ))
        await db.commit()

    async def no_materials(*args, **kwargs):
        return []
    async def no_roster(*args, **kwargs):
        return ""
    async def memory_tools():
        return [{"key": "remember", "description": "Remember synthetic preference"}]
    monkeypatch.setattr(knowledge, "retrieve_scoped", no_materials)
    monkeypatch.setattr(arslan, "_team_roster", no_roster)
    monkeypatch.setattr(arslan, "_arslan_tools", memory_tools)
    monkeypatch.setitem(tool_loop.EXECUTORS, "remember", RememberExecutor())

    class Adapter:
        def __init__(self):
            self.requests = []
            self.pending = None

        async def chat(self, system, user, **kwargs):
            self.requests.append({"system": system, "user": user})
            if self.pending is not None:
                content, self.pending = self.pending, None
                return LLMResponse(content="", usage={}, tool_calls=[{
                    "id": "fixture-save", "type": "function", "function": {
                        "name": "remember", "arguments": {
                            "kind": "preference", "action": "append", "content": content,
                        },
                    },
                }])
            return LLMResponse(content="Synthetic response; not a graded model answer.", usage={})
    adapter = Adapter()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    @task_context.scoped_turn
    async def turn(conversation_id, user_message, emit):
        # No router/model intent claim: exercise the actual host answer entry.
        message_id = await memory.add_message(conversation_id, "user", user_message)
        task_context.source_message(message_id)
        return await arslan._handle_answer(conversation_id, user_message, emit)

    async def run(conversation_id, message, *, save=None):
        assert personal_context.current() is None
        adapter.pending = save
        start = len(adapter.requests)
        events = []
        await turn(conversation_id, message, events.append)
        assert personal_context.current() is None
        assert not any(event["type"] == "error" for event in events)
        assert len(adapter.requests) > start
        return adapter.requests[start:]
    return run


@pytest.mark.parametrize("scenario_id,content", [
    ("M01-01", "I prefer English reports."),
    ("M01-02", "报告先给结论。"),
    ("M01-04", "do not use emoji in professional reports."),
    ("M01-05", "review summaries need outcome, risks, and next steps."),
])
async def test_explicit_save_reaches_next_task_prompt_and_receipt(
    scenario_id, content, runtime, execution_db,
):
    scenario = SCENARIOS[scenario_id]
    await runtime("first", scenario["turns"][0]["content"], save=content)
    async with repository() as repo:
        entries = await repo.list_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "active" and entry["content"] == content
    assert entry["confirmed_at"]
    source = entry["sources"][0]
    assert source["author"] == "user" and source["kind"] == "user_message"
    async with execution_db() as db:
        message = await db.get(ArslanMessage, source["reference"]["message_id"])
    assert message.content == scenario["turns"][0]["content"]
    second = await runtime("second", scenario["turns"][1]["content"])
    assert content in second[0]["system"]
    async with execution_db() as db:
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "second"))).all()
        runs = (await db.scalars(select(Run))).all()
    assert any(any(ref["id"] == entry["id"] for ref in row.receipt["used"]) for row in receipts)
    assert runs and all(run.status == "completed" for run in runs)


@pytest.mark.parametrize("no_learning", [False, True], ids=["M02-03", "M02-05"])
async def test_nonexplicit_or_disabled_learning_never_confirms_next_task_memory(
    no_learning, runtime, execution_db,
):
    content = "Use option A for unrelated screens"
    if no_learning:
        async with execution_db() as db:
            db.add(ConversationContext(id="first", no_learning=True))
            await db.commit()
    await runtime("first", "I choose option A for this screen.", save=content)
    async with repository() as repo:
        entries = await repo.list_entries()
    if no_learning:
        assert entries == []
    else:
        assert len(entries) == 1 and entries[0]["status"] == "proposed"
    second = await runtime("second", "Design an unrelated screen.")
    assert content not in second[0]["system"]


async def test_disabled_memory_is_not_sent_and_is_not_deleted(runtime, execution_db):
    # M02-06: trusted task setting, not a model-inferred permission.
    content = "Use concise report conclusions."
    await runtime("first", f"Remember: {content}", save=content)
    async with execution_db() as db:
        db.add(ConversationContext(id="second", no_memory=True))
        await db.commit()
    second = await runtime("second", "Prepare a report without personal memory.")
    assert content not in second[0]["system"]
    async with repository() as repo:
        assert (await repo.list_entries())[0]["content"] == content
    third = await runtime("third", "Prepare a normal report.")
    assert content in third[0]["system"]


async def test_project_identity_is_reloaded_for_each_task(runtime, execution_db):
    # M03-01/03/05: same display name must not merge distinct project IDs.
    async with execution_db() as db:
        db.add_all([Project(id="project-a", name="Notes"), Project(id="project-b", name="Notes")])
        await db.flush()
        db.add_all([ConversationContext(id="a-save", project_id="project-a"),
                    ConversationContext(id="b-save", project_id="project-b"),
                    ConversationContext(id="a-read", project_id="project-a"),
                    ConversationContext(id="b-read", project_id="project-b")])
        await db.commit()
    orange = "Project Notes uses orange release diagrams."
    blue = "Project Notes uses blue release diagrams."
    await runtime("a-save", f"Remember: {orange}", save=orange)
    await runtime("b-save", f"Remember: {blue}", save=blue)
    a = await runtime("a-read", "Design for Notes.")
    b = await runtime("b-read", "Design for Notes.")
    unassigned = await runtime("unassigned", "Design for Notes.")
    assert orange in a[0]["system"] and blue not in a[0]["system"]
    assert blue in b[0]["system"] and orange not in b[0]["system"]
    assert orange not in unassigned[0]["system"] and blue not in unassigned[0]["system"]
    async with execution_db() as db:
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "b-read"))).all()
    async with repository() as repo:
        entries = await repo.list_entries()
    a_ids = {entry["id"] for entry in entries if entry["scope"]["id"] == "project-a"}
    assert a_ids and receipts
    assert not any(ref["id"] in a_ids for receipt in receipts for ref in receipt.receipt["used"])


@pytest.mark.parametrize("deleted", [False, True], ids=["M06-01", "M06-02-context-only"])
async def test_disable_or_delete_excludes_later_host_prompt(runtime, deleted):
    content = "Use small red headings for reports."
    await runtime("save", f"Remember: {content}", save=content)
    async with repository() as repo:
        entry = (await repo.list_entries())[0]
        if deleted:
            await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
        else:
            paused = await repo.set_status(entry["id"], entry["version"], "paused", MemoryActor(origin="user"))
            assert await repo.history(entry["id"])
    later = await runtime("later", "Prepare a report.")
    assert content not in later[0]["system"]
    if not deleted:
        async with repository() as repo:
            await repo.set_status(entry["id"], paused["version"], "active", MemoryActor(origin="user"))
        restored = await runtime("restored", "Prepare a report.")
        assert content in restored[0]["system"]


async def test_real_task_receipt_reviews_old_revision_but_never_resurrects_deleted_memory(
    runtime, execution_db, monkeypatch,
):
    # M06-07: actual host-generated receipt through authenticated review HTTP,
    # followed by another real host task. No browser/native rendering claim.
    import httpx
    from fastapi import FastAPI
    from server import auth
    from server.api.companion import router

    original = "Use green report headings and concise conclusions."
    updated = "Use blue report headings and concise conclusions."
    await runtime("receipt-save", f"Remember: {original}", save=original)
    used = await runtime("receipt-used", "Prepare a report with headings.")
    assert all(original in request["system"] for request in used)
    async with repository() as repo:
        entry = (await repo.list_entries())[0]
        changed = await repo.revise(entry["id"], entry["version"], MemoryWrite(
            content=updated, scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    async with execution_db() as db:
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "receipt-used"))).all()
    assert receipts and all(row.receipt["used"] for row in receipts)
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-receipt-review")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    base = "/api/v1/conversations/receipt-used/context/receipts"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-receipt-review"}) as client:
        for receipt in receipts:
            path = f"{base}/{receipt.id}/memories/{entry['id']}"
            response = await client.get(path)
            assert response.status_code == 200
            value = response.json()
            assert value["status"] == "available" and value["content"] == original
            assert value["recorded_version"] == entry["version"]
            assert value["current_version"] == changed["version"]
        async with repository() as repo:
            await repo.delete_entry(entry["id"], changed["version"], MemoryActor(origin="user"))
        for receipt in receipts:
            response = await client.get(f"{base}/{receipt.id}/memories/{entry['id']}")
            assert response.status_code == 200
            assert response.json()["status"] == "deleted" and response.json()["content"] is None
            assert original not in response.text and updated not in response.text
        listed = await client.get(base)
        assert listed.status_code == 200
        assert {row["id"] for row in listed.json()} == {row.id for row in receipts}
        assert original not in listed.text and updated not in listed.text
    later = await runtime("receipt-after-delete", "Prepare another report with headings.")
    assert all(original not in request["system"] and updated not in request["system"] for request in later)
    async with execution_db() as db:
        after = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "receipt-after-delete"))).all()
    assert after and all(not row.receipt["used"] for row in after)
    async with repository() as repo:
        assert all(row["content"] is None for row in await repo.history(entry["id"]))


async def test_summary_regeneration_excludes_deleted_memory_sources_from_later_task(
    runtime, execution_db, monkeypatch,
):
    # M06-03: run the real compaction/history path; only the summarizer's
    # response is scripted, and every summarizer input is inspected.
    from server.db.models import ArslanSummary

    content = "Use violet report headings as my permanent report preference."
    conversation = "summary-deletion"
    await runtime(conversation, f"Remember: {content}", save=content)
    last = await memory.add_message(conversation, "assistant", f"Saved preference: {content}")
    async with execution_db() as db:
        db.add(ArslanSummary(conversation_id=conversation, summary=f"Old summary: {content}",
                             up_to_message_id=last))
        await db.commit()
    async with repository() as repo:
        entry = (await repo.list_entries())[0]
        await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
    async with execution_db() as db:
        assert not (await db.scalars(select(ArslanSummary))).all()
        # Deleting memory does not silently erase the user's displayed chat.
        originals = (await db.scalars(select(ArslanMessage).where(
            ArslanMessage.conversation_id == conversation))).all()
        assert any(content in message.content for message in originals)
    await memory.add_message(conversation, "user", "Prepare an inventory report for this task.")
    await memory.add_message(conversation, "assistant", "This task concerns an inventory report.")
    await memory.add_message(conversation, "user", "Regenerate the working summary.")
    summarizer_requests = []
    class Summarizer:
        async def chat(self, system, user, **kwargs):
            summarizer_requests.append(user)
            return LLMResponse(content="Current task: prepare an inventory report.", usage={})
    monkeypatch.setattr(memory, "_get_adapter", lambda: Summarizer())
    monkeypatch.setattr(memory, "_token_budget", lambda: 1)
    monkeypatch.setattr(memory, "_summary_token_cap", lambda: 200)
    await memory.maybe_compact(conversation)
    assert summarizer_requests
    assert all(content not in request and "Old summary" not in request for request in summarizer_requests)
    assert "inventory report" in summarizer_requests[0]
    async with execution_db() as db:
        regenerated = (await db.scalars(select(ArslanSummary).where(
            ArslanSummary.conversation_id == conversation))).all()
    assert regenerated and all(content not in row.summary for row in regenerated)
    monkeypatch.setattr(memory, "_token_budget", lambda: 2000)
    async with execution_db() as db:
        previous_receipts = (await db.scalars(select(ContextReceiptRecord.id))).all()
    later = await runtime(conversation, "Continue the current inventory report.")
    assert all(content not in str(request) for request in later)
    assert any("inventory report" in str(request) for request in later)
    async with execution_db() as db:
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == conversation,
            ContextReceiptRecord.id.not_in(previous_receipts)))).all()
    assert receipts and all(not row.receipt["used"] for row in receipts)


async def test_local_only_memory_is_filtered_from_cloud_prompt(runtime, execution_db):
    # M07-07 outbound boundary; adapter is synthetic, no provider request occurs.
    content = "Keep my private report naming preference local."
    await runtime("local", f"Remember: {content}", save=content)
    async with execution_db() as db:
        await db.execute(update(ProviderConfig).values(provider="openai", base_url="", model="fixture-cloud"))
        db.add(ConversationContext(id="cloud", cloud_memory_allowed=True, allow_sensitive=True))
        await db.commit()
    cloud = await runtime("cloud", "Prepare a report.")
    assert content not in cloud[0]["system"]
    async with repository() as repo:
        assert (await repo.list_entries())[0]["content"] == content


@pytest.mark.parametrize("cloud_allowed,sensitive_allowed", [(False, False), (False, True), (True, False), (True, True)])
async def test_sensitive_project_memory_needs_both_task_permissions(
    cloud_allowed, sensitive_allowed, runtime, execution_db,
):
    # M07-07: trusted saved permissions, actual outbound synthetic-adapter input.
    content = "Synthetic sensitive project report preference: blue headings."
    async with execution_db() as db:
        db.add(Project(id="sensitive-project", name="Sensitive fixture"))
        await db.flush()
        db.add(ConversationContext(id="sensitive-task", project_id="sensitive-project",
                                   cloud_memory_allowed=cloud_allowed, allow_sensitive=sensitive_allowed))
        await db.execute(update(ProviderConfig).values(provider="openai", base_url="", model="fixture-cloud"))
        await db.commit()
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="project", id="sensitive-project"),
                                             sensitivity="sensitive", sensitive_acknowledged=True,
                                             use_policy="cloud_allowed"), MemoryActor(origin="user"))
    requests = await runtime("sensitive-task", "Prepare a project report with headings.")
    expected = cloud_allowed and sensitive_allowed
    assert all((content in request["system"]) == expected for request in requests)
    async with execution_db() as db:
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "sensitive-task"))).all()
    assert receipts
    assert all(any(ref["id"] == entry["id"] for ref in row.receipt["used"]) == expected for row in receipts)
    async with repository() as repo:
        retained = await repo.present(await repo.get(entry["id"]))
    assert retained["status"] == "active" and retained["content"] == content


async def test_restored_memory_is_absent_from_next_host_request_until_fresh_review(runtime, execution_db):
    # M06-05: exercise the real restore quarantine service and host prompt, not
    # archive I/O (covered by the separate frozen restore harness).
    from server.services.memory_restore import mark_restored_sync

    content = "Use concise reports with blue headings."
    await runtime("before-restore", f"Remember: {content}", save=content)
    async with repository() as repo:
        entry = (await repo.list_entries())[0]
    async with execution_db.kw["bind"].begin() as connection:
        result = await connection.run_sync(mark_restored_sync)
    assert result["review_required"] and result["quarantined_entries"] == 1
    after = await runtime("after-restore", "Prepare a report with headings.")
    assert all(content not in request["system"] for request in after)
    async with execution_db() as db:
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "after-restore"))).all()
    assert receipts and all(not row.receipt["used"] for row in receipts)
    async with repository() as repo:
        restored = await repo.present(await repo.get(entry["id"]))
        assert restored["status"] == "quarantined" and restored["content"] == content
        await repo.revise(entry["id"], restored["version"], MemoryWrite(
            content=content, scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    reviewed = await runtime("after-review", "Prepare a report with headings.")
    assert content in reviewed[0]["system"]


@pytest.mark.parametrize("record_source", ["imported", "current_installation"])
async def test_later_deletion_manifest_blocks_old_backup_in_actual_host_request(
    runtime, execution_db, tmp_path, monkeypatch, record_source,
):
    # M06-04: real archive/staged reconciliation, then a new host task bound to
    # the restored DB. No model/transport behavior is inferred from the script.
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from arslan.companion.memory import MemoryError
    from server.db import session as db_session
    from server.services import backup, memory_deletion_manifest

    content = "For reports use concise conclusions and blue headings."
    await runtime("pre-backup", f"Remember: {content}", save=content)
    async with repository() as repo:
        entry = (await repo.list_entries())[0]
    archive = tmp_path / "before-delete.zip"
    backup.create(tmp_path, archive, db_path=tmp_path / "execution.db")
    original = archive.read_bytes()
    async with repository() as repo:
        await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
    async with execution_db.kw["bind"].begin() as connection:
        manifest = await connection.run_sync(memory_deletion_manifest.export_sync)
    restored = tmp_path / "restored-profile"
    options = {"deletion_manifest": manifest} if record_source == "imported" else {
        "current_db_path": tmp_path / "execution.db"}
    outcome = backup.restore(archive, restored, **options)
    assert outcome["deletion_reconciliation"]["deleted_entries"] == 1
    if record_source == "current_installation":
        assert outcome["deletion_record_selection"]["local_ledger_present"] is True
    assert archive.read_bytes() == original
    engine = db_session.build_engine(f"sqlite+aiosqlite:///{restored / 'arslan.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(db_session, "AsyncSessionLocal", maker)
            requests = await runtime("post-restore-new-task", "Prepare a report with headings.")
            assert all(content not in request["system"] and content not in request["user"] for request in requests)
            async with maker() as db:
                receipts = (await db.scalars(select(ContextReceiptRecord).where(
                    ContextReceiptRecord.conversation_id == "post-restore-new-task"))).all()
            assert receipts and all(not row.receipt["used"] for row in receipts)
            async with repository() as repo:
                item = await repo.present(await repo.get(entry["id"]))
                assert item["status"] == "deleted" and item["content"] is None
                history = await repo.history(entry["id"])
                assert all(row["content"] is None for row in history)
            with pytest.raises(MemoryError, match="^memory_previously_deleted$"):
                async with repository() as repo:
                    await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global")),
                                      MemoryActor(origin="user"))
    finally:
        await engine.dispose()


async def test_repeated_save_keeps_one_active_entry(runtime):
    # M01-06: exact equivalent content, not a semantic-paraphrase claim.
    content = "concise reports"
    await runtime("first", f"Remember: {content}", save=content)
    await runtime("second", SCENARIOS["M01-06"]["turns"][0]["content"], save=content)
    async with repository() as repo:
        entries = await repo.list_entries()
    assert len(entries) == 1 and entries[0]["status"] == "active"
    later = await runtime("third", SCENARIOS["M01-06"]["turns"][1]["content"])
    assert later[0]["system"].count(entries[0]["id"]) == 1


@pytest.mark.parametrize("scenario_id,project,original,candidate,later_query", [
    ("M02-01", False, "Use concise reports.", "Use detailed reports.", "Prepare another report."),
    ("M02-02", True, "Use orange for project design.", "Use blue for project design.",
     "Create another project design."),
])
async def test_one_off_instruction_does_not_replace_later_task_memory(
    scenario_id, project, original, candidate, later_query, runtime, execution_db,
):
    # The scripted model deliberately tries to save its interpretation. This
    # proves the runtime boundary, not whether a real model follows the request.
    if project:
        async with execution_db() as db:
            db.add(Project(id="one-off-project", name="Project A"))
            await db.flush()
            db.add_all([ConversationContext(id=cid, project_id="one-off-project")
                        for cid in ("save", "one-off", "later")])
            await db.commit()
    await runtime("save", f"Remember: {original}", save=original)
    async with repository() as repo:
        initial = (await repo.list_entries())[0]
    instruction = SCENARIOS[scenario_id]["turns"][0]["content"]
    current = await runtime("one-off", instruction, save=candidate)
    assert instruction in current[0]["user"]
    async with repository() as repo:
        entries = await repo.list_entries()
        retained = next(entry for entry in entries if entry["id"] == initial["id"])
        assert retained["content"] == original and retained["version"] == initial["version"]
        assert retained["status"] == "active"
        proposed = [entry for entry in entries if entry["content"] == candidate]
        assert len(proposed) == 1 and proposed[0]["status"] == "proposed"
    later = await runtime("later", later_query)
    assert original in later[0]["system"]
    assert candidate not in later[0]["system"]
    assert instruction not in later[0]["user"]
    async with execution_db() as db:
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "later"))).all()
    used = {ref["id"] for receipt in receipts for ref in receipt.receipt["used"]}
    assert initial["id"] in used and proposed[0]["id"] not in used


@pytest.mark.parametrize("credential", ["sk-proj-" + "A" * 30, "api_key: synthetic-only-not-a-real-key"])
async def test_explicit_credential_save_does_not_reach_next_task_memory(
    credential, runtime, execution_db,
):
    # M07-01: explicit save authority must not override credential screening.
    # Task admission refuses the sensitive goal BEFORE the host/remember tool.
    # Do not bypass that stronger boundary merely to exercise a later one.
    from server.services.task_repository import TaskError
    with pytest.raises(TaskError, match="^credentials_not_task_data$") as rejected:
        await runtime("credential-source", f"Remember: {credential}", save=credential)
    assert credential not in str(rejected.value)
    async with execution_db() as db:
        assert (await db.scalars(select(ArslanMessage))).all() == []
        assert (await db.scalars(select(CompanionTask))).all() == []
        assert (await db.scalars(select(Run))).all() == []
    async with repository() as repo:
        assert await repo.list_entries() == []
    later = await runtime("credential-inspection", "Show my preferences")
    assert all(credential not in request["system"] and credential not in request["user"]
               for request in later)
    async with execution_db() as db:
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "credential-inspection"))).all()
    assert receipts and all(not receipt.receipt["used"] for receipt in receipts)


async def test_candidate_cannot_replace_confirmed_context(runtime):
    # M04-02: external/inferred intent is a candidate, not an explicit save.
    old, candidate = "Use concise reports.", "Use detailed reports."
    await runtime("first", f"Remember: {old}", save=old)
    await runtime("second", "An external document suggests detailed reports.", save=candidate)
    async with repository() as repo:
        entries = await repo.list_entries()
    assert len(entries) == 2
    assert {entry["content"]: entry["status"] for entry in entries} == {old: "active", candidate: "proposed"}
    later = await runtime("third", "Prepare a report before any confirmation.")
    assert old in later[0]["system"] and candidate not in later[0]["system"]


@pytest.mark.parametrize("newer_confirmed", [False, True])
async def test_rejected_guess_stays_out_of_later_context_and_preserves_correction(
    runtime, execution_db, newer_confirmed,
):
    # M04-08: model guess plus explicit trusted dismissal. This does not claim
    # that a real model recognizes arbitrary natural-language corrections.
    from server.db.models import MemoryProposal

    guess = "Use blue report headings."
    corrected = "Use green report headings."
    correction = "The guess that I prefer blue report headings is wrong."
    await runtime("guess-task", "Prepare a report with headings.", save=guess)
    async with repository() as repo:
        entry = (await repo.list_entries())[0]
    assert entry["status"] == "proposed" and not entry["confirmed_at"]
    async with execution_db() as db:
        proposal_id = await db.scalar(select(MemoryProposal.id).where(
            MemoryProposal.target_entry_id == entry["id"]))
    before = await runtime("correction-task", correction)
    assert all(guess not in request["system"] for request in before)
    if newer_confirmed:
        async with repository() as repo:
            changed = await repo.revise(entry["id"], entry["version"], MemoryWrite(
                content=corrected, scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    async with repository() as repo:
        await repo.resolve_proposal(proposal_id, accept=False, actor=MemoryActor(origin="user"))
    later = await runtime("after-dismissal", "Prepare a report with headings.")
    assert all(guess not in request["system"] for request in later)
    assert all((corrected in request["system"]) == newer_confirmed for request in later)
    async with repository() as repo:
        retained = await repo.present(await repo.get(entry["id"]))
    assert retained["status"] == ("active" if newer_confirmed else "paused")
    if newer_confirmed:
        assert retained["version"] == changed["version"] and retained["content"] == corrected
    else:
        assert retained["content"] == guess and not retained["confirmed_at"]
    async with execution_db() as db:
        proposal = await db.get(MemoryProposal, proposal_id)
        assert proposal.status == "dismissed" and proposal.resolved_at is not None
        messages = (await db.scalars(select(ArslanMessage).where(
            ArslanMessage.conversation_id == "correction-task", ArslanMessage.role == "user"))).all()
        assert any(message.content == correction for message in messages)
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "after-dismissal"))).all()
    assert receipts
    if newer_confirmed:
        assert all(any(ref["id"] == entry["id"] and ref["revision"] == changed["version"]
                       for ref in row.receipt["used"]) for row in receipts)
    else:
        assert all(not row.receipt["used"] for row in receipts)


async def test_user_revision_replaces_prompt_but_retains_history(runtime):
    # M04-01: exact old/new UI operation, not permission inferred by a model.
    old, new = "Use detailed reports.", "Use concise reports."
    await runtime("first", f"Remember: {old}", save=old)
    async with repository() as repo:
        entry = (await repo.list_entries())[0]
        changed = await repo.revise(entry["id"], entry["version"],
                                   MemoryWrite(content=new, scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
        assert changed["version"] == 2
        assert [item["content"] for item in await repo.history(entry["id"])] == [new, old]
    later = await runtime("second", "Prepare a report.")
    assert new in later[0]["system"] and old not in later[0]["system"]


@pytest.mark.parametrize("via_proposals", [False, True], ids=["M04-03", "M04-06"])
async def test_stale_edit_or_conflicting_confirmation_cannot_change_next_task_context(
    runtime, execution_db, via_proposals,
):
    from arslan.companion.memory import MemoryError
    from server.db.models import MemoryProposal

    old = "Use detailed reports with green headings."
    chosen = "Use concise reports with blue headings."
    stale = "Use lengthy reports with red headings."
    user = MemoryActor(origin="user")
    await runtime("initial-save", f"Remember: {old}", save=old)
    async with repository() as repo:
        entry = (await repo.list_entries())[0]
    chosen_write = MemoryWrite(content=chosen, scope=MemoryScope(kind="global"))
    stale_write = MemoryWrite(content=stale, scope=MemoryScope(kind="global"))
    if via_proposals:
        # Two candidates for the same target/version; trusted UI review is
        # represented by the repository call, not inferred from model prose.
        async with repository() as repo:
            first = await repo.revise(entry["id"], entry["version"], chosen_write,
                                      MemoryActor(origin="host"))
            second = await repo.revise(entry["id"], entry["version"], stale_write,
                                       MemoryActor(origin="host"))
        before = await runtime("before-review", "Prepare a report with headings.")
        assert all(old in request["system"] and chosen not in request["system"]
                   and stale not in request["system"] for request in before)
        async with repository() as repo:
            changed = await repo.resolve_proposal(first["proposal_id"], accept=True, actor=user)
        with pytest.raises(MemoryError, match="^memory_version_conflict$"):
            async with repository() as repo:
                await repo.resolve_proposal(second["proposal_id"], accept=True, actor=user)
        async with execution_db() as db:
            accepted = await db.get(MemoryProposal, first["proposal_id"])
            pending = await db.get(MemoryProposal, second["proposal_id"])
            assert accepted.status == "accepted" and pending.status == "pending"
    else:
        async with repository() as repo:
            changed = await repo.revise(entry["id"], entry["version"], chosen_write, user)
        with pytest.raises(MemoryError, match="^memory_version_conflict$"):
            async with repository() as repo:
                await repo.revise(entry["id"], entry["version"], stale_write, user)
    assert changed["version"] == entry["version"] + 1
    later = await runtime("after-stale-refusal", "Prepare a report with headings.")
    assert all(chosen in request["system"] and old not in request["system"]
               and stale not in request["system"] for request in later)
    async with repository() as repo:
        current = await repo.present(await repo.get(entry["id"]))
        history = await repo.history(entry["id"])
    assert current["version"] == changed["version"] and current["content"] == chosen
    assert [row["content"] for row in history] == [chosen, old]
    async with execution_db() as db:
        receipts = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "after-stale-refusal"))).all()
    assert receipts
    assert all(any(ref["id"] == entry["id"] and ref["revision"] == changed["version"]
                   for ref in row.receipt["used"]) for row in receipts)


@pytest.mark.parametrize("field", ["valid_from", "expires_at"], ids=["M05-01", "M05-04"])
async def test_effective_time_changes_later_task_context(runtime, monkeypatch, field):
    # Clock advances at the actual personal-context selection boundary.
    content = "Use the summer report template."
    now = datetime.utcnow()
    boundary = now + timedelta(days=1)
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global"),
                                             **{field: boundary.replace(tzinfo=UTC)}), MemoryActor(origin="user"))
    first = await runtime("before", "Prepare a report.")
    assert (content in first[0]["system"]) is (field == "expires_at")

    class Later(datetime):
        @classmethod
        def utcnow(cls):
            return boundary + timedelta(seconds=1)
    monkeypatch.setattr(personal_context, "datetime", Later)
    second = await runtime("after", "Prepare a report.")
    assert (content in second[0]["system"]) is (field == "valid_from")
    async with repository() as repo:
        assert (await repo.history(entry["id"]))[0]["content"] == content


@pytest.mark.parametrize("query", [
    "What is 2 + 2?", "2加2等于多少？", "2 + 2 は何ですか？", "¿Cuánto es 2 + 2?",
    "Was ist 2 + 2?", "Combien font 2 + 2 ?", "Write a code patch.",
])
async def test_unrelated_memory_is_absent_from_actual_next_host_request(runtime, execution_db, query):
    # M08-02 and M03-06: not merely hidden from the recall tool's results.
    content = ("For reports use concise conclusions." if query == "Write a code patch."
               else "For design work use orange minimalist layouts.")
    await runtime("save-design", f"Remember: {content}", save=content)
    later = await runtime("unrelated", query)
    assert content not in later[0]["system"]
    async with execution_db() as db:
        receipt = await db.scalar(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "unrelated"))
    assert receipt.receipt["used"] == []
    assert "irrelevant" in receipt.receipt["filter_reasons"]
    # Exclusion is task-local, not deletion or permanent memory disablement.
    related = await runtime("related", "Prepare a report." if query == "Write a code patch." else "Design a new layout.")
    assert content in related[0]["system"]


@pytest.mark.parametrize("query", [
    "Prepare a report", "准备一份报告", "レポートを書いて", "Prepara un informe",
    "Erstelle einen Bericht", "Prépare un rapport",
])
async def test_english_report_preference_reaches_related_task_in_each_locale(runtime, query):
    content = "I prefer concise English reports."
    await runtime("save-report", f"Remember: {content}", save=content)
    later = await runtime("related-report", query)
    assert content in later[0]["system"]
