"""Media execution is separate from style memory and source-file permission."""
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Awaitable, Callable, Literal, Protocol

from pydantic import Field, model_validator

from arslan.companion.contracts import Contract


class MediaError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ImageRequest(Contract):
    prompt: Annotated[str, Field(min_length=1, max_length=4000)]
    negative_prompt: Annotated[str, Field(max_length=1000)] = ""
    width: Annotated[int, Field(ge=256, le=1024, strict=True)] = 512
    height: Annotated[int, Field(ge=256, le=1024, strict=True)] = 512
    steps: Annotated[int, Field(ge=1, le=40, strict=True)] = 20
    seed: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)] = 0

    @model_validator(mode="after")
    def bounded_dimensions(self):
        if not self.prompt.strip() or self.width % 64 or self.height % 64:
            raise ValueError("media_invalid_request")
        return self


class ModelPin(Contract):
    checkpoint: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.safetensors$")]
    revision: Annotated[str, Field(min_length=1, max_length=100)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    license_name: Annotated[str, Field(min_length=1, max_length=100)]
    license_source: Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=1000)]
    required_memory_bytes: Annotated[int, Field(gt=0, le=128 * 1024**3, strict=True)]


@dataclass(frozen=True)
class LocalMediaConfig:
    """Provisioned by trusted host setup, never parsed from model/tool arguments.

    The external runtime/model is not bundled or downloaded. Execution defaults
    off pending the host confirmation/boundary integration, independently of a
    successful read-only preflight.
    """
    runtime_root: Path
    model: ModelPin
    execution_enabled: bool = False


class MediaJob(Contract):
    id: Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")]
    owner_id: Annotated[str, Field(min_length=1, max_length=100)]
    task_id: Annotated[str, Field(min_length=1, max_length=200)]
    run_id: Annotated[int, Field(gt=0, strict=True)]
    request: ImageRequest
    model: ModelPin
    runtime_commit: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    intent_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    status: Literal["prepared", "submitting", "queued", "uncertain", "cancel_requested", "cancelled", "produced", "output_ready", "failed"] = "prepared"
    error_code: str | None = None


@dataclass(frozen=True)
class MediaArtifact:
    filename: str
    data: bytes
    sha256: str
    width: int
    height: int
    intent_hash: str
    model_sha256: str


# The host journal must durably compare-and-swap expected → updated. A stale
# snapshot must raise, never replace newer state. None means insert-if-absent.
PersistJob = Callable[[MediaJob | None, MediaJob], Awaitable[None]]


class MediaBackend(Protocol):
    def capabilities(self) -> dict: ...
    async def preflight(self) -> dict: ...
    def estimate(self, request: ImageRequest) -> dict: ...
    async def generate(self, job: MediaJob, *, owner_id: str, task_id: str, run_id: int, approved_intent_hash: str) -> MediaJob: ...
    async def edit(self, *args, **kwargs) -> MediaJob: ...
    async def reconcile(self, job: MediaJob, *, owner_id: str, task_id: str, run_id: int) -> MediaJob: ...
    async def cancel(self, job: MediaJob, *, owner_id: str, task_id: str, run_id: int) -> MediaJob: ...
    async def artifacts(self, job: MediaJob, *, owner_id: str, task_id: str, run_id: int) -> list[MediaArtifact]: ...
