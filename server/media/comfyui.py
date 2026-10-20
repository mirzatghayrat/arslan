"""The local ComfyUI backend, as metadata only: the runtime it was pinned to (v0.35.0) and what is
implemented, which is nothing.

The restricted adapter that was here (ComfyUIBackend, its journal and contracts) was never wired
to a host: there was no execution endpoint. It was removed in v0.1.63 (C2e-2); git history has it.
`capabilities()` answers GET /connections/local-media/capabilities and no longer claims generation.
"""
from __future__ import annotations

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
            "implemented": {"generate": False, "edit": False, "targeted_cancel": False, "verified_png": False},
            "local": {"generate": False, "edit": False},
            "blocked_reason": "media_host_setup_required", "automatic_install": False,
            "cloud_reference_upload": False, "video_generation": False}
