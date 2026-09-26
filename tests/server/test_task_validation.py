import io
import sys
import zipfile

import pytest

from arslan.companion.contracts import AcceptanceCheck, ResourceRef, TaskSpec
from arslan.models import LLMResponse
from server.orchestrator import tool_loop
from server.resources.artifact_inspector import inspect
from server.services import artifact_store, artifact_validation, execution_context, host_run, task_service, task_validation
from server.services.task_repository import TaskError, repository


def check(kind="text", **rule):
    return AcceptanceCheck.model_validate({"id": "expected", "description": "Check fixture", "evaluator": "deterministic",
                                          "rule": {"kind": kind, **rule}})


async def run_contract(checks, body):
    spec = TaskSpec.model_validate({"id": "validate-task", "instruction": "Check fixture", "locale": "en",
        "scope": {"kind": "task", "owner_id": "local", "task_id": "validate-task"},
        "acceptance": [item.model_dump() for item in checks]})
    async with repository() as repo:
        created = await repo.create(spec, "validation")
        started = await repo.start(spec.id, created["version"])
    return await task_service._launch(started, lambda event: None, body)


@pytest.mark.parametrize("kind,text,rule,expected", [
    ("text", "wrong", {"equals": "right"}, "failed"),
    ("text", "right", {"equals": "right"}, "passed"),
    ("text", "value", {"contains": ["missing"]}, "failed"),
    ("text", "abc", {"minimum": 2, "maximum": 3}, "passed"),
    ("json", '{"value":2}', {"equals": '{"value":1}'}, "failed"),
    ("json", '{"value":2}', {"contains": ["value"]}, "passed"),
    ("json", "not JSON", {}, "failed"),
    ("code_build", "Build passed", {}, "not_run"),
    ("code_test", "All tests passed", {}, "not_run"),
    ("language", "English", {"locale": "en"}, "not_run"),
    ("layout", "Looks perfect", {}, "not_run"),
    ("remote_readback", "App/locale updated", {}, "not_run"),
])
def test_declarative_checks_do_not_accept_claims_instead_of_proof(kind, text, rule, expected):
    assert task_validation.evaluate(check(kind, **rule), text, [], [])["status"] == expected


def test_source_count_requires_successful_open_not_search_or_model_urls():
    assertion = check("research_sources", minimum=1, target="https://fixture.invalid")
    search = {"tool": "web_search", "args": {"url": "https://fixture.invalid"}, "result": {"ok": True}}
    assert task_validation.evaluate(assertion, "I opened https://fixture.invalid", [], [search])["status"] == "failed"
    from arslan.companion.research import receipt
    opened = {**search, "tool": "web_extract", "result": {"ok": True, "url": "https://fixture.invalid", "text": "Body",
        "source": receipt("https://fixture.invalid", "Body", truncated=False).model_dump(mode="json")}}
    assert task_validation.evaluate(assertion, "", [], [opened])["status"] == "passed"
    assert task_validation.evaluate(assertion, "", [], [{**opened, "result": {"ok": False}}])["status"] == "failed"


def test_build_checks_match_exact_admitted_command_and_actual_value():
    assertion = check("code_test", target="python", argv=["-m", "pytest", "tests"], contains=["12 passed"])
    receipt = {"tool": "run_command", "args": {"command": "python", "argv": ["-m", "pytest", "tests"]},
               "result": {"ok": True, "exit_code": 0, "stdout": "12 passed"}}
    assert task_validation.evaluate(assertion, "", [], [receipt])["status"] == "passed"
    wrong_value = {**receipt, "result": {"ok": True, "exit_code": 0, "stdout": "no tests ran"}}
    assert task_validation.evaluate(assertion, "", [], [wrong_value])["status"] == "failed"
    wrong_command = {**receipt, "args": {"command": "echo", "argv": ["12 passed"]}}
    assert task_validation.evaluate(assertion, "", [], [wrong_command])["status"] == "not_run"


def test_rule_fields_cannot_be_silently_ignored_and_artifact_count_is_checked():
    with pytest.raises(ValueError, match="not supported"):
        check("text", target="file-that-was-never-read.txt", equals="answer")
    with pytest.raises(ValueError, match="not supported"):
        check("artifact", contains=["text-that-was-never-read"])
    artifact = {"id": "one", "filename": "one.txt", "status": "passed"}
    assert task_validation.evaluate(check("artifact", minimum=2), "", [artifact], [])["status"] == "failed"


@pytest.mark.parametrize("suffix,data,status", [
    (".txt", b"", "failed"), (".json", b"{broken", "failed"),
    (".png", b"not PNG", "failed"), (".pdf", b"not PDF", "failed"),
    (".docx", b"broken", "failed"), (".unknown", b"unparsed", "not_run"),
    (".csv", b"a,b\n1,2", "passed"),
])
async def test_file_parse_distinguishes_corrupt_empty_and_unsupported(monkeypatch, tmp_path, suffix, data, status):
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path)
    async def parser(content, extension):
        try:
            return inspect(content, extension)
        except Exception:
            return {"status": "failed", "code": "artifact_parse_failed"}
    monkeypatch.setattr(artifact_validation, "inspect_bytes", parser)
    artifact = artifact_store.store_bytes(7, "fixture" + suffix, data)
    assert (await artifact_validation.validate(7, artifact["filename"]))["status"] == status


def test_office_container_and_image_dimensions_are_structural_not_visual_checks():
    container = io.BytesIO()
    with zipfile.ZipFile(container, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    with pytest.raises(Exception):
        inspect(container.getvalue(), ".docx")
    from docx import Document
    valid = io.BytesIO()
    document = Document()
    document.add_paragraph("Fixture")
    document.save(valid)
    assert inspect(valid.getvalue(), ".docx")["code"] == "office_document_parsed"
    from PIL import Image
    image = io.BytesIO()
    Image.new("RGB", (20, 30)).save(image, "PNG")
    parsed = inspect(image.getvalue(), ".png")
    assert parsed["width"] == 20 and parsed["height"] == 30
    artifact = {**parsed, "id": "artifact", "filename": "fixture.png"}
    assert task_validation.evaluate(check("image_dimensions", width=21), "", [artifact], [])["status"] == "failed"


async def test_integrity_rejects_tampering_links_and_false_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "store")
    artifact = artifact_store.store_bytes(7, "fixture.txt", b"original")
    path = artifact_store.root() / artifact["filename"]
    path.write_bytes(b"modified")
    assert (await artifact_validation.validate(7, artifact["filename"]))["status"] == "failed"
    path.unlink()
    secret = tmp_path / "private"
    secret.write_text("synthetic private canary")
    path.symlink_to(secret)
    with pytest.raises((ValueError, OSError)):
        artifact_store.read_owned(7, artifact["filename"])
    with pytest.raises(ValueError):
        artifact_store.read_owned(8, artifact["filename"])


async def test_native_validation_repairs_once_then_succeeds_with_evidence(execution_db, monkeypatch):
    prompts = []
    class Adapter:
        async def chat(self, system, user, **kwargs):
            prompts.append(user)
            return LLMResponse(usage={}, content="wrong" if len(prompts) == 1 else "right")
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    async def tools():
        return []
    async def body(emit):
        return await tool_loop.run_native(system="Check", user_content="fixture", history=[], resolve_tools=tools,
            emit=emit, on_chunk=lambda text: None, allow_escalation=False)
    result = await run_contract([check(equals="right")], body)
    assert result["final"] == "right" and len(prompts) == 2
    assert "Deterministic validation failed" in prompts[1]
    async with repository() as repo:
        task = await repo.get("validate-task")
        assert task.phase == "succeeded" and task.results[0]["status"] == "passed"
        assert task.results[0]["evidence"]
        assert len((await repo.latest_checkpoint(task.id))["progress"]["validation_repairs"]) == 1


async def test_repeated_failed_repair_stops_and_never_accepts(execution_db, monkeypatch):
    count = 0
    class Adapter:
        async def chat(self, *args, **kwargs):
            nonlocal count
            count += 1
            return LLMResponse(usage={}, content="still wrong")
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    async def tools():
        return []
    async def body(emit):
        return await tool_loop.run_native(system="Check", user_content="fixture", history=[], resolve_tools=tools,
            emit=emit, on_chunk=lambda text: None, allow_escalation=False)
    await run_contract([check(equals="right")], body)
    assert count == 2
    async with repository() as repo:
        task = await repo.get("validate-task")
        assert task.phase == "waiting_user" and task.pause_reason == "task_validation_failed"
        with pytest.raises(TaskError):
            await repo.accept_review(task.id, task.version)


@pytest.mark.parametrize("prefix", ["", "https://untrusted.invalid"])
async def test_missing_artifact_link_cannot_be_accepted(execution_db, prefix):
    async def body(emit):
        return f"[Made it]({prefix}/api/v1/runs/999/artifacts/run_999_missing.pdf)"
    manual = AcceptanceCheck(id="review", description="Review output", evaluator="human")
    await run_contract([manual], body)
    async with repository() as repo:
        task = await repo.get("validate-task")
        report = await task_validation.latest_report(repo, task)
        assert task.pause_reason == "task_validation_failed"
        assert report["artifacts"][0]["code"] == "artifact_scope_denied"


async def test_manual_acceptance_preserves_deterministic_proof(execution_db):
    async def body(emit):
        return "right"
    await run_contract([check(equals="right"), AcceptanceCheck(id="review", description="Review", evaluator="human")], body)
    async with repository() as repo:
        task = await repo.get("validate-task")
        before = task.results[0]
        result = await repo.accept_review(task.id, task.version)
        assert result["state"]["phase"] == "succeeded"
        assert result["state"]["results"][0] == before


async def test_file_changed_after_checks_requires_new_review(execution_db, monkeypatch, tmp_path):
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "artifacts")
    async def parser(data, suffix):
        return {"status": "passed", "code": "text_parsed"}
    monkeypatch.setattr(artifact_validation, "inspect_bytes", parser)
    saved = []
    async def body(emit):
        async def host(sink):
            artifact = artifact_store.store_bytes(execution_context.current_run_id(), "fixture.txt", b"saved")
            saved.append(artifact)
            runtime = task_service.current()
            runtime.progress = runtime.progress.model_copy(update={"artifacts": (ResourceRef(
                id=artifact["id"], kind="artifact", revision=1, sha256=artifact["sha256"], locator=artifact["url"]),)})
            return "File prepared"
        return await host_run.execute("validation", "fixture", emit, host)
    await run_contract([AcceptanceCheck(id="review", description="Review", evaluator="human")], body)
    (artifact_store.root() / saved[0]["filename"]).write_text("changed")
    async with repository() as repo:
        task = await repo.get("validate-task")
        with pytest.raises(TaskError, match="artifact_changed"):
            await repo.accept_review(task.id, task.version)


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt file parser")
async def test_actual_isolated_parser_handles_json_without_external_access():
    assert await artifact_validation.inspect_bytes(b'{"value":1}', ".json") == {
        "status": "passed", "code": "text_parsed", "characters": 11}


async def test_parser_never_falls_back_without_isolation(monkeypatch):
    monkeypatch.setattr(artifact_validation.code_sandbox, "_seatbelt_wrapper", lambda profile: None)
    assert (await artifact_validation.inspect_bytes(b"text", ".txt"))["status"] == "not_run"


async def test_explicitly_conditional_check_can_be_not_applicable(execution_db):
    async def body(emit):
        return "No file requested"
    conditional = check("artifact", when="artifacts_present")
    await run_contract([conditional, AcceptanceCheck(id="review", description="Review", evaluator="human")], body)
    async with repository() as repo:
        task = await repo.get("validate-task")
        assert task.results[0]["status"] == "not_applicable"
        assert (await repo.accept_review(task.id, task.version))["state"]["phase"] == "succeeded"


async def test_model_assessment_cannot_replace_deterministic_checks(execution_db, monkeypatch):
    judgments = []
    class Adapter:
        async def chat(self, system, user, **kwargs):
            judgments.append(user)
            return LLMResponse(usage={}, content='{"passed":true}')
    model = AcceptanceCheck(id="style", description="Readable", evaluator="model")
    async def body(emit):
        await task_validation.validate_output(task_service.current(), "wrong", [], model_adapter=Adapter())
        return "wrong"
    await run_contract([check(equals="right"), model], body)
    assert judgments == []
    async with repository() as repo:
        task = await repo.get("validate-task")
        assert task.phase != "succeeded"
        assert [item["status"] for item in task.results] == ["failed", "not_run"]


def test_failed_artifact_links_are_not_revealed_as_downloads():
    proposed = "[Missing](/api/v1/runs/999/artifacts/run_999_missing.pdf)"
    report = {"artifacts": [{"status": "failed", "code": "artifact_scope_denied"}]}
    rendered = task_validation.failure_output(proposed, report, "zh")
    assert "/api/" not in rendered and "文件未验证" in rendered and "尚未验收" in rendered


async def test_missing_deterministic_backend_remains_resumable_not_accepted(execution_db):
    async def body(emit):
        return "A screenshot description is not a screenshot check"
    await run_contract([check("layout")], body)
    async with repository() as repo:
        task = await repo.get("validate-task")
        assert task.phase == "waiting_user" and task.pause_reason == "task_checks_not_run"


async def test_actual_model_assessment_is_noncritical_and_has_a_receipt(execution_db):
    class Adapter:
        async def chat(self, system, user, **kwargs):
            assert kwargs["tools"] is None and "untrusted data" in system
            return LLMResponse(usage={}, content='{"passed":true}')
    async def body(emit):
        await task_validation.validate_output(task_service.current(), "right", [], model_adapter=Adapter())
        return "right"
    await run_contract([check(equals="right"), AcceptanceCheck(id="style", description="Readable", evaluator="model")], body)
    async with repository() as repo:
        task = await repo.get("validate-task")
        assert task.phase == "succeeded"
        assert all(item["evidence"] for item in task.results)


async def test_final_wrapper_cannot_replace_an_already_checked_output(execution_db):
    async def body(emit):
        await task_validation.validate_output(task_service.current(), "right", [])
        return "wrong"
    await run_contract([check(equals="right")], body)
    async with repository() as repo:
        task = await repo.get("validate-task")
        assert task.phase == "waiting_user" and task.results[0]["status"] == "failed"


@pytest.mark.parametrize("old_state,explicit_old", [("corrupt", False), ("missing", False), ("corrupt", True)])
async def test_repaired_artifact_revisions_preserve_history_without_hiding_explicit_links(
        execution_db, monkeypatch, tmp_path, old_state, explicit_old):
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "artifacts")
    async def parser(data, suffix):
        try:
            return inspect(data, suffix)
        except Exception:
            return {"status": "failed", "code": "artifact_parse_failed"}
    monkeypatch.setattr(artifact_validation, "inspect_bytes", parser)
    async def body(emit):
        async def host(sink):
            saved = []
            runtime = task_service.current()
            for index, data in enumerate((b"broken JSON", b'{"value":1}')):
                async def execute(admitted_args):
                    artifact = artifact_store.store_bytes(execution_context.current_run_id(), "result.json", data)
                    saved.append(artifact)
                    return {"ok": True, "artifact": artifact}
                await runtime.execute_tool("run_python", {"fixture_revision": index}, execute)
            if old_state == "missing":
                (artifact_store.root() / saved[0]["filename"]).unlink()
            output = f"[Repaired file]({saved[1]['url']})"
            if explicit_old:
                output += f"\n[Also deliver the old file]({saved[0]['url']})"
            return output
        return await host_run.execute("validation", "fixture", emit, host)
    await run_contract([check("artifact", target="result.json")], body)
    async with repository() as repo:
        task = await repo.get("validate-task")
        report = await task_validation.latest_report(repo, task)
        assert len(report["artifacts"]) == 2
        if explicit_old:
            assert task.phase == "waiting_user" and report["artifacts"][0]["status"] == "failed"
        else:
            assert task.phase == "succeeded" and report["artifacts"][0]["status"] == "not_applicable"
            assert report["artifacts"][0]["superseded_by"] == report["artifacts"][1]["id"]
