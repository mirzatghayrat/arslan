"""Restricted local ComfyUI adapter, checked against the immutable v0.35.0 API.

No runtime source is bundled. This client never installs nodes/models, calls an
API/cloud node, or uses the global interrupt route. The host must durably persist
every job transition and provide the exact user-approved intent digest. There is
deliberately no public/model-callable execution endpoint until that host boundary
is integrated and reviewed.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import stat
import subprocess
from uuid import uuid4

import httpx
from PIL import Image, UnidentifiedImageError

from server.media.contracts import ImageRequest, LocalMediaConfig, MediaArtifact, MediaError, MediaJob, PersistJob

RUNTIME_VERSION = "0.35.0"
RUNTIME_COMMIT = "40c4fcdf513a4523e39d54a9d391908af8df8171"
API_SOURCE = f"https://github.com/Comfy-Org/ComfyUI/blob/{RUNTIME_COMMIT}/server.py"
BASE_URL = "http://127.0.0.1:8188"
NODES = ("CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage", "KSampler", "VAEDecode", "SaveImage")
MAX_JSON = 1024 * 1024
MAX_IMAGE = 20 * 1024 * 1024


def capabilities() -> dict:
    return {"backend": "comfyui-local", "runtime_version": RUNTIME_VERSION, "runtime_commit": RUNTIME_COMMIT,
            "api_source": API_SOURCE, "runtime_license": "GPL-3.0", "runtime_bundled": False,
            "interface": ["capabilities", "preflight", "estimate", "generate", "edit", "cancel", "artifacts"],
            "implemented": {"generate": True, "edit": False, "targeted_cancel": True, "verified_png": True},
            "local": {"generate": False, "edit": False},
            "blocked_reason": "media_host_setup_required", "automatic_install": False,
            "cloud_reference_upload": False, "video_generation": False}


def _runtime_and_model(config: LocalMediaConfig) -> str | None:
    """Read-only runtime pin and checkpoint-byte verification, never model load."""
    root = config.runtime_root
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                                text=True, timeout=3, env={"PATH": "/usr/bin:/bin", "HOME": str(root)})
        if result.returncode or result.stdout.strip() != RUNTIME_COMMIT:
            return "media_runtime_pin_mismatch"
        clean = subprocess.run(["git", "-C", str(root), "-c", "core.fsmonitor=false", "diff", "--no-ext-diff", "--no-textconv", "--quiet", "HEAD"], timeout=3,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env={"PATH": "/usr/bin:/bin", "HOME": str(root), "GIT_OPTIONAL_LOCKS": "0"})
        if clean.returncode:
            return "media_runtime_pin_mismatch"
        # Relative directory handles reject symlink escapes, including parents.
        handles = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
        try:
            for name in ("models", "checkpoints"):
                handles.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=handles[-1]))
            fd = os.open(config.model.checkpoint, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=handles[-1])
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 20 * 1024**3:
                    return "media_model_unavailable"
                digest = hashlib.sha256()
                total = 0
                while chunk := stream.read(min(1024 * 1024, info.st_size + 1 - total)):
                    total += len(chunk)
                    if total > info.st_size:
                        return "media_model_pin_mismatch"
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
                if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    return "media_model_pin_mismatch"
                if digest.hexdigest() != config.model.sha256:
                    return "media_model_pin_mismatch"
        finally:
            for handle in reversed(handles):
                os.close(handle)
    except (OSError, subprocess.TimeoutExpired):
        return "media_model_unavailable"
    return None


class ComfyUIBackend:
    def __init__(self, config: LocalMediaConfig | None, persist: PersistJob, *, transport=None):
        self.config, self.persist = config, persist
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=5, follow_redirects=False,
                                       trust_env=False, transport=transport,
                                       limits=httpx.Limits(max_connections=2, max_keepalive_connections=1))

    async def close(self):
        await self.client.aclose()

    def capabilities(self) -> dict:
        value = capabilities()
        value["configured"] = self.config is not None
        # An enabled setup is still not a verified runnable device/model.
        value["execution_gate_enabled"] = bool(self.config and self.config.execution_enabled)
        value["local"]["generate"] = value["execution_gate_enabled"]
        value["readiness"] = "not_checked"
        return value

    async def _read(self, method: str, path: str, *, limit=MAX_JSON, **kwargs) -> bytes:
        try:
            return await asyncio.wait_for(self._read_bounded(method, path, limit=limit, **kwargs), timeout=10)
        except TimeoutError as exc:
            raise MediaError("media_backend_timeout") from exc

    async def _read_bounded(self, method: str, path: str, *, limit: int, **kwargs) -> bytes:
        async with self.client.stream(method, path, **kwargs) as response:
            if response.is_redirect:
                raise MediaError("media_redirect_refused")
            if response.status_code == 404:
                raise MediaError("media_job_unknown")
            if response.status_code >= 400:
                raise MediaError("media_backend_rejected")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise MediaError("media_response_too_large")
            return bytes(body)

    async def _json(self, method: str, path: str, **kwargs) -> dict:
        try:
            value = json.loads(await self._read(method, path, **kwargs))
        except (ValueError, UnicodeDecodeError) as exc:
            if isinstance(exc, MediaError):
                raise
            raise MediaError("media_invalid_response") from exc
        if not isinstance(value, dict):
            raise MediaError("media_invalid_response")
        return value

    async def preflight(self) -> dict:
        if self.config is None:
            return {"ready": False, "reason": "media_not_configured", "model_loaded": False}
        issue = await asyncio.to_thread(_runtime_and_model, self.config)
        if issue:
            return {"ready": False, "reason": issue, "model_loaded": False}
        try:
            stats = await self._json("GET", "/system_stats")
            if stats.get("system", {}).get("comfyui_version") != RUNTIME_VERSION:
                return {"ready": False, "reason": "media_runtime_pin_mismatch", "model_loaded": False}
            devices = stats.get("devices", [])
            available = max((int(item.get("vram_total", 0)) for item in devices if isinstance(item, dict)), default=0)
            if available < self.config.model.required_memory_bytes:
                return {"ready": False, "reason": "media_hardware_insufficient", "model_loaded": False}
            for name in NODES:
                info = (await self._json("GET", f"/object_info/{name}")).get(name, {})
                if info.get("python_module") != "nodes":
                    return {"ready": False, "reason": "media_core_node_mismatch", "model_loaded": False}
                if name == "CheckpointLoaderSimple":
                    choices = info.get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
                    if self.config.model.checkpoint not in choices:
                        return {"ready": False, "reason": "media_model_unavailable", "model_loaded": False}
            return {"ready": True, "reason": None, "model_loaded": False, "execution_enabled": self.config.execution_enabled,
                    "model_revision": self.config.model.revision, "model_sha256": self.config.model.sha256,
                    "license_name": self.config.model.license_name, "license_source": self.config.model.license_source}
        except (httpx.HTTPError, MediaError, ValueError, TypeError, IndexError, AttributeError):
            return {"ready": False, "reason": "media_backend_unavailable", "model_loaded": False}

    def estimate(self, request: ImageRequest) -> dict:
        return {"images": 1, "width": request.width, "height": request.height, "steps": request.steps,
                "pixel_steps": request.width * request.height * request.steps,
                "seconds": None, "money": None, "reason": "media_estimate_not_calibrated",
                "downloads": 0, "cloud_uploads": 0}

    @staticmethod
    def _intent(job: dict) -> str:
        fields = {key: job[key] for key in ("id", "owner_id", "task_id", "run_id", "request", "model", "runtime_commit")}
        return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    async def prepare(self, request: ImageRequest, *, owner_id: str, task_id: str, run_id: int) -> MediaJob:
        if self.config is None:
            raise MediaError("media_not_configured")
        fields = {"id": str(uuid4()), "owner_id": owner_id, "task_id": task_id, "run_id": run_id,
                  "request": request.model_dump(mode="json"), "model": self.config.model.model_dump(mode="json"), "runtime_commit": RUNTIME_COMMIT}
        job = MediaJob.model_validate({**fields, "intent_hash": self._intent(fields)})
        await self.persist(None, job)
        return job

    def _own(self, job: MediaJob, owner_id: str, task_id: str, run_id: int):
        if (owner_id, task_id, run_id) != (job.owner_id, job.task_id, job.run_id):
            raise MediaError("media_job_scope_denied")
        if self._intent(job.model_dump(mode="json")) != job.intent_hash:
            raise MediaError("media_job_pin_changed")

    async def _state(self, job: MediaJob, status: str, code: str | None = None) -> MediaJob:
        updated = MediaJob.model_validate({**job.model_dump(), "status": status, "error_code": code})
        await self.persist(job, updated)  # Durable CAS BEFORE any following remote write.
        return updated

    def _workflow(self, job: MediaJob) -> dict:
        r = job.request
        return {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": job.model.checkpoint}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": r.prompt, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": r.negative_prompt, "clip": ["1", 1]}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": r.width, "height": r.height, "batch_size": 1}},
            "5": {"class_type": "KSampler", "inputs": {"seed": r.seed, "steps": r.steps, "cfg": 7.0,
                "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0, "model": ["1", 0],
                "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": f"arslan_{job.id}"}},
        }

    async def generate(self, job: MediaJob, *, owner_id: str, task_id: str, run_id: int, approved_intent_hash: str) -> MediaJob:
        self._own(job, owner_id, task_id, run_id)
        if not self.config or not self.config.execution_enabled or approved_intent_hash != job.intent_hash:
            raise MediaError("media_approval_required")
        if job.model != self.config.model or job.runtime_commit != RUNTIME_COMMIT:
            raise MediaError("media_job_pin_changed")
        if job.status != "prepared":
            raise MediaError("media_reconciliation_required")
        report = await self.preflight()
        if not report["ready"]:
            raise MediaError(report["reason"])
        pending = await self._state(job, "submitting")
        try:
            result = await self._json("POST", "/prompt", json={"prompt": self._workflow(job), "prompt_id": job.id})
            if result.get("prompt_id") != job.id or result.get("node_errors"):
                return await self._state(pending, "uncertain", "media_submission_uncertain")
        except (httpx.HTTPError, MediaError):
            # No automatic resubmission, even when a timeout looks like failure.
            return await self._state(pending, "uncertain", "media_submission_uncertain")
        return await self._state(pending, "queued")

    async def edit(self, *args, **kwargs) -> MediaJob:
        # Unmasked img2img would change unrelated pixels. Do not pass that off
        # as the specified-edit contract until mask/compositing is implemented.
        raise MediaError("media_precise_edit_unavailable")

    async def reconcile(self, job: MediaJob, *, owner_id: str, task_id: str, run_id: int) -> MediaJob:
        """Observe one owned job; missing history never authorizes resubmission."""
        self._own(job, owner_id, task_id, run_id)
        if job.status in {"prepared", "cancelled", "failed", "output_ready"}:
            return job
        await self.persist(job, job)  # Validate durable ownership before remote reads.
        result = await self._json("GET", f"/api/jobs/{job.id}")
        if result.get("id") != job.id:
            raise MediaError("media_output_scope_denied")
        status = result.get("status")
        if status in {"pending", "in_progress"}:
            target = "cancel_requested" if job.status == "cancel_requested" else "queued"
        elif status == "completed":
            # Still requires separate byte-level artifact verification.
            target = "produced"
        elif status in {"failed", "cancelled"}:
            target = status
        else:
            raise MediaError("media_invalid_response")
        return await self._state(job, target, "media_generation_failed" if target == "failed" else None)

    async def cancel(self, job: MediaJob, *, owner_id: str, task_id: str, run_id: int) -> MediaJob:
        self._own(job, owner_id, task_id, run_id)
        if job.status == "prepared":
            return await self._state(job, "cancelled")
        if job.status in {"cancelled", "failed", "output_ready"}:
            return job
        pending = await self._state(job, "cancel_requested")
        try:
            result = await self._json("POST", f"/api/jobs/{job.id}/cancel")
        except (httpx.HTTPError, MediaError):
            return await self._state(pending, "cancel_requested", "media_cancel_uncertain")
        # A dispatched interrupt is not proof that the running job has stopped.
        return await self._state(pending, "cancel_requested", None if result.get("cancelled") is True else "media_reconciliation_required")

    async def artifacts(self, job: MediaJob, *, owner_id: str, task_id: str, run_id: int) -> list[MediaArtifact]:
        self._own(job, owner_id, task_id, run_id)
        if job.status in {"prepared", "cancelled", "failed"}:
            raise MediaError("media_output_not_ready")
        await self.persist(job, job)  # Reject invented/stale job objects before fetching bytes.
        history = await self._json("GET", f"/history/{job.id}")
        record = history.get(job.id)
        if not isinstance(record, dict) or not isinstance(record.get("status"), dict):
            raise MediaError("media_output_not_ready")
        if record["status"].get("completed") is not True:
            raise MediaError("media_output_not_ready")
        if record["status"].get("status_str") != "success":
            raise MediaError("media_generation_failed")
        outputs = record.get("outputs")
        if not isinstance(outputs, dict) or not isinstance(outputs.get("7"), dict):
            raise MediaError("media_output_invalid")
        images = outputs["7"].get("images", [])
        if not isinstance(images, list) or len(images) != 1:
            raise MediaError("media_output_invalid")
        item = images[0]
        if not isinstance(item, dict):
            raise MediaError("media_output_invalid")
        name = item.get("filename", "")
        if (not isinstance(name, str) or not name.startswith(f"arslan_{job.id}_") or not name.endswith(".png")
                or len(name) > 200 or any(part in name for part in ("/", "\\", "..", "\x00"))
                or item.get("subfolder", "") != "" or item.get("type") != "output"):
            raise MediaError("media_output_scope_denied")
        data = await self._read("GET", "/view", params={"filename": name, "type": "output", "subfolder": ""}, limit=MAX_IMAGE)
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or image.size != (job.request.width, job.request.height):
                    raise MediaError("media_output_invalid")
                image.verify()
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise MediaError("media_output_invalid") from exc
        await self._state(job, "output_ready")
        return [MediaArtifact(name, data, hashlib.sha256(data).hexdigest(), job.request.width,
                              job.request.height, job.intent_hash, job.model.sha256)]
