import asyncio
import hashlib
import io
import json
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest
from pydantic import ValidationError

from server.media import comfyui
from server.media.contracts import ImageRequest, LocalMediaConfig, MediaError, ModelPin
from server.media.journal import MediaJournal

SCOPE = {"owner_id": "user", "task_id": "task-a", "run_id": 1}


@pytest.fixture
def model():
    return ModelPin(checkpoint="test.safetensors", revision="test-revision", sha256="a" * 64,
                    license_name="test-only", license_source="https://example.test/license", required_memory_bytes=1024)


@pytest.fixture
async def setup(tmp_path, model, monkeypatch):
    calls = []
    responses = {}

    def handler(request):
        calls.append(request)
        value = responses.get((request.method, request.url.path))
        if callable(value):
            return value(request)
        if value is not None:
            return httpx.Response(200, json=value)
        if request.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {"comfyui_version": comfyui.RUNTIME_VERSION}, "devices": [{"vram_total": 2048}]})
        if request.url.path.startswith("/object_info/"):
            name = request.url.path.rsplit("/", 1)[1]
            return httpx.Response(200, json={name: {"python_module": "nodes", "input": {"required": {"ckpt_name": [[model.checkpoint]]}}}})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": json.loads(request.content)["prompt_id"]})
        return httpx.Response(404)

    monkeypatch.setattr(comfyui, "_runtime_and_model", lambda config: None)
    journal = MediaJournal(tmp_path / "media.sqlite")
    backend = comfyui.ComfyUIBackend(LocalMediaConfig(tmp_path, model, True), journal.persist,
                                    transport=httpx.MockTransport(handler))
    job = await backend.prepare(ImageRequest(prompt="Synthetic test image"), **SCOPE)
    yield backend, journal, job, calls, responses
    await backend.close()


async def submit(setup):
    backend, _, job, _, _ = setup
    return await backend.generate(job, **SCOPE, approved_intent_hash=job.intent_hash)


async def test_prepare_is_durable_and_approval_bound_to_unique_job(setup):
    backend, journal, job, calls, _ = setup
    assert await journal.get(job.id, **SCOPE) == job
    second = await backend.prepare(job.request, **SCOPE)
    assert second.intent_hash != job.intent_hash and not calls
    with pytest.raises(MediaError, match="media_approval_required"):
        await backend.generate(second, **SCOPE, approved_intent_hash=job.intent_hash)
    assert not calls


async def test_fixed_workflow_and_stale_snapshot_cannot_resubmit_after_restart(setup):
    backend, journal, job, calls, _ = setup
    queued = await submit(setup)
    assert queued.status == "queued"
    sent = json.loads(next(call.content for call in calls if call.method == "POST"))
    assert sent["prompt_id"] == job.id
    assert {node["class_type"] for node in sent["prompt"].values()} == set(comfyui.NODES)
    assert sent["prompt"]["4"]["inputs"]["batch_size"] == 1
    reopened = MediaJournal(journal.path)
    assert await reopened.get(job.id, **SCOPE) == queued
    with pytest.raises(MediaError, match="media_job_stale"):
        await backend.generate(job, **SCOPE, approved_intent_hash=job.intent_hash)
    assert sum(call.url.path == "/prompt" for call in calls) == 1


async def test_concurrent_submission_only_sends_once(setup):
    backend, _, job, calls, _ = setup
    results = await asyncio.gather(*(backend.generate(job, **SCOPE, approved_intent_hash=job.intent_hash) for _ in range(2)), return_exceptions=True)
    assert sum(isinstance(value, MediaError) for value in results) == 1
    assert sum(call.url.path == "/prompt" for call in calls) == 1


async def test_timeout_remains_uncertain_and_never_retries(setup):
    backend, journal, job, calls, responses = setup
    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)
    responses["POST", "/prompt"] = timeout
    uncertain = await submit(setup)
    assert uncertain.status == "uncertain"
    with pytest.raises(MediaError, match="media_reconciliation_required"):
        await backend.generate(uncertain, **SCOPE, approved_intent_hash=job.intent_hash)
    with pytest.raises(MediaError, match="media_job_unknown"):
        await backend.reconcile(uncertain, **SCOPE)
    assert (await journal.get(job.id, **SCOPE)).status == "uncertain"
    assert sum(call.url.path == "/prompt" for call in calls) == 1


@pytest.mark.parametrize("field,value", [("owner_id", "foreign"), ("task_id", "foreign"), ("run_id", 2)])
async def test_scope_checked_before_network_or_read(setup, field, value):
    backend, journal, job, calls, _ = setup
    scope = {**SCOPE, field: value}
    for action in (backend.cancel, backend.reconcile, backend.artifacts):
        with pytest.raises(MediaError, match="media_job_scope_denied"):
            await action(job, **scope)
    with pytest.raises(MediaError, match="media_job_scope_denied"):
        await journal.get(job.id, **scope)
    assert not calls


async def test_invented_and_stale_jobs_cannot_read_remote_output(setup):
    backend, _, job, calls, _ = setup
    invented = job.model_copy(update={"status": "queued"})
    for action in (backend.reconcile, backend.artifacts):
        with pytest.raises(MediaError, match="media_job_stale"):
            await action(invented, **SCOPE)
    assert not calls


async def test_execution_gate_and_pin_rechecked_before_submission(setup):
    backend, _, job, calls, _ = setup
    config = backend.config
    backend.config = LocalMediaConfig(config.runtime_root, config.model, False)
    with pytest.raises(MediaError, match="media_approval_required"):
        await backend.generate(job, **SCOPE, approved_intent_hash=job.intent_hash)
    backend.config = LocalMediaConfig(config.runtime_root, config.model.model_copy(update={"sha256": "b" * 64}), True)
    with pytest.raises(MediaError, match="media_job_pin_changed"):
        await backend.generate(job, **SCOPE, approved_intent_hash=job.intent_hash)
    assert not calls


async def test_targeted_cancel_waits_for_authoritative_completion(setup):
    backend, _, job, calls, responses = setup
    queued = await submit(setup)
    responses["POST", f"/api/jobs/{job.id}/cancel"] = {"cancelled": True}
    requested = await backend.cancel(queued, **SCOPE)
    assert requested.status == "cancel_requested"
    responses["GET", f"/api/jobs/{job.id}"] = {"id": job.id, "status": "in_progress"}
    pending = await backend.reconcile(requested, **SCOPE)
    assert pending.status == "cancel_requested"
    responses["GET", f"/api/jobs/{job.id}"] = {"id": job.id, "status": "cancelled"}
    assert (await backend.reconcile(pending, **SCOPE)).status == "cancelled"
    assert all(call.url.path != "/interrupt" for call in calls)


async def test_prepared_cancel_is_local_and_edit_explicitly_unsupported(setup):
    backend, _, job, calls, _ = setup
    assert (await backend.cancel(job, **SCOPE)).status == "cancelled"
    with pytest.raises(MediaError, match="media_precise_edit_unavailable"):
        await backend.edit()
    assert not calls


@pytest.mark.parametrize("status,target", [("completed", "produced"), ("failed", "failed"), ("pending", "queued")])
async def test_reconciliation_states(setup, status, target):
    backend, _, job, _, responses = setup
    queued = await submit(setup)
    responses["GET", f"/api/jobs/{job.id}"] = {"id": job.id, "status": status}
    assert (await backend.reconcile(queued, **SCOPE)).status == target


def output_response(job):
    return {job.id: {"status": {"completed": True, "status_str": "success"},
                     "outputs": {"7": {"images": [{"filename": f"arslan_{job.id}_00001_.png", "type": "output", "subfolder": ""}]}}}}


async def test_verified_artifact_contains_pin_and_content_hash(setup):
    backend, journal, job, _, responses = setup
    queued = await submit(setup)
    responses["GET", f"/history/{job.id}"] = output_response(job)
    buffer = io.BytesIO()
    Image.new("RGB", (512, 512), "blue").save(buffer, format="PNG")
    data = buffer.getvalue()
    responses["GET", "/view"] = lambda request: httpx.Response(200, content=data)
    artifacts = await backend.artifacts(queued, **SCOPE)
    assert artifacts[0].sha256 == hashlib.sha256(data).hexdigest()
    assert artifacts[0].intent_hash == job.intent_hash and artifacts[0].model_sha256 == job.model.sha256
    assert (await journal.get(job.id, **SCOPE)).status == "output_ready"


@pytest.mark.parametrize("mutation", ["traversal", "other_job", "malformed_status", "malformed_outputs", "corrupt", "wrong_dimensions", "redirect", "oversize"])
async def test_unsafe_artifacts_rejected_without_success_state(setup, mutation, monkeypatch):
    backend, journal, job, calls, responses = setup
    queued = await submit(setup)
    history = output_response(job)
    record = history[job.id]
    if mutation == "traversal":
        record["outputs"]["7"]["images"][0]["filename"] += "/../x.png"
    elif mutation == "other_job":
        record["outputs"]["7"]["images"][0]["filename"] = "arslan_other.png"
    elif mutation == "malformed_status":
        record["status"] = None
    elif mutation == "malformed_outputs":
        record["outputs"] = []
    responses["GET", f"/history/{job.id}"] = history
    data = b"not an image"
    if mutation == "wrong_dimensions":
        buffer = io.BytesIO()
        Image.new("RGB", (256, 256)).save(buffer, format="PNG")
        data = buffer.getvalue()
    if mutation == "oversize":
        monkeypatch.setattr(comfyui, "MAX_IMAGE", 8)
    responses["GET", "/view"] = lambda request: httpx.Response(302, headers={"location": "https://example.test"}) if mutation == "redirect" else httpx.Response(200, content=data)
    with pytest.raises(MediaError):
        await backend.artifacts(queued, **SCOPE)
    assert (await journal.get(job.id, **SCOPE)).status == "queued"
    assert all(call.url.host == "127.0.0.1" for call in calls)


@pytest.mark.parametrize("payload", [None, [], {"system": []}, {"system": {"comfyui_version": "wrong"}}, {"system": {"comfyui_version": comfyui.RUNTIME_VERSION}, "devices": []}])
async def test_preflight_malformed_or_incompatible_backend_fails_closed(setup, payload):
    backend, _, _, calls, responses = setup
    responses["GET", "/system_stats"] = lambda request: httpx.Response(200, json=payload)
    assert not (await backend.preflight())["ready"]
    assert not any(call.method == "POST" for call in calls)


@pytest.mark.parametrize("values", [{"width": 257}, {"width": 2048}, {"steps": 41}, {"seed": -1}, {"prompt": " "}, {"width": True}])
def test_request_limits(values):
    with pytest.raises(ValidationError):
        ImageRequest(**{"prompt": "test", **values})


def test_model_requires_license_and_exact_hash(model):
    values = model.model_dump()
    for key in ("license_name", "license_source", "sha256", "revision"):
        with pytest.raises(ValidationError):
            ModelPin.model_validate({name: value for name, value in values.items() if name != key})


async def test_unconfigured_backend_does_not_probe_network(tmp_path):
    journal = MediaJournal(tmp_path / "media.sqlite")
    def forbidden(request):
        pytest.fail("unconfigured adapter must not probe services")
    backend = comfyui.ComfyUIBackend(None, journal.persist, transport=httpx.MockTransport(forbidden))
    try:
        assert not (await backend.preflight())["ready"]
        assert not backend.capabilities()["local"]["generate"]
        assert backend.estimate(ImageRequest(prompt="test"))["seconds"] is None
    finally:
        await backend.close()


@pytest.mark.parametrize("case,expected", [("valid", None), ("hash", "media_model_pin_mismatch"),
    ("symlink", "media_model_unavailable"), ("dirty", "media_runtime_pin_mismatch"),
    ("commit", "media_runtime_pin_mismatch"), ("empty", "media_model_unavailable")])
def test_runtime_checkpoint_bytes_and_symlinks(tmp_path, model, monkeypatch, case, expected):
    checkpoints = tmp_path / "models" / "checkpoints"
    checkpoints.mkdir(parents=True)
    fixture = b"synthetic checkpoint bytes, not a model"
    filename = checkpoints / model.checkpoint
    if case == "symlink":
        target = tmp_path / "outside"
        target.write_bytes(fixture)
        filename.symlink_to(target)
    else:
        filename.write_bytes(b"" if case == "empty" else fixture)
    pin = model.model_copy(update={"sha256": "f" * 64 if case == "hash" else hashlib.sha256(fixture).hexdigest()})
    calls = []
    def git(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(returncode=1 if case == "dirty" and "diff" in arguments else 0,
                               stdout="bad" if case == "commit" else comfyui.RUNTIME_COMMIT)
    monkeypatch.setattr(comfyui.subprocess, "run", git)
    assert comfyui._runtime_and_model(LocalMediaConfig(tmp_path, pin)) == expected
    assert all(arguments[0] == "git" for arguments in calls)


@pytest.mark.parametrize("node,info,expected", [
    ("KSampler", {"python_module": "custom_nodes"}, "media_core_node_mismatch"),
    ("CheckpointLoaderSimple", {"python_module": "nodes", "input": {"required": {"ckpt_name": [["other.safetensors"]]}}}, "media_model_unavailable"),
])
async def test_preflight_rejects_custom_node_or_missing_checkpoint(setup, node, info, expected):
    backend, _, _, _, responses = setup
    responses["GET", f"/object_info/{node}"] = {node: info}
    result = await backend.preflight()
    assert not result["ready"] and result["reason"] == expected
