"""Arslan's own pinned runtimes for installed capabilities (0.1.57 §5.1).

The packaged app ships neither uv nor Node. When a capability needs one, Arslan downloads
the version pinned HERE from its official release URL, checks the SHA-256 pinned here, and
unpacks it under `data_dir/runtimes/`. Nothing is taken from PATH for installs: what a
capability runs on is exactly what this file names. Apple silicon only (Arslan's builds are
darwin-aarch64); elsewhere `available()` says so.

Updating a pin = changing version + url + sha256 together (the sha from the release's own
.sha256 / SHASUMS256.txt, checked 2026-10-09 for the values below).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import platform
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pin:
    name: str
    version: str
    url: str
    sha256: str
    size_mb: int
    folder: str          # the top folder inside the archive ("" = files at the top)
    binaries: tuple[str, ...]


PINS = {
    "uv": Pin("uv", "0.12.23",
              "https://github.com/astral-sh/uv/releases/download/0.12.23/uv-aarch64-apple-darwin.tar.gz",
              "50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544", 20,
              "uv-aarch64-apple-darwin", ("uv",)),
    "node": Pin("node", "24.21.0",
                "https://nodejs.org/dist/v24.21.0/node-v24.21.0-darwin-arm64.tar.gz",
                "bed7eea5325e1108f32ce5228ddd6a5f0f08a499ee42aa7442aea583702f6057", 50,
                "node-v24.21.0-darwin-arm64", ("bin/node", "bin/npm")),
}

_locks: dict[str, asyncio.Lock] = {}


class RuntimeFailure(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


def root() -> Path:
    from server import config
    return config.data_dir() / "runtimes"


def available() -> bool:
    return platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64")


def home(name: str) -> Path:
    pin = PINS[name]
    return root() / f"{pin.name}-{pin.version}"


def binary(name: str, which: str | None = None) -> Path:
    pin = PINS[name]
    base = home(name) / pin.folder if pin.folder else home(name)
    return base / (which or pin.binaries[0])


def ready(name: str) -> bool:
    return all(binary(name, b).is_file() for b in PINS[name].binaries)


def _safe_members(archive: tarfile.TarFile, dest: Path):
    """No member may land outside dest (absolute paths, .., or links pointing out)."""
    base = dest.resolve()
    for member in archive.getmembers():
        target = (dest / member.name).resolve()
        if not target.is_relative_to(base):
            raise RuntimeFailure("archive_escapes", member.name)
        if member.issym() or member.islnk():
            link = (target.parent / member.linkname).resolve()
            if not link.is_relative_to(base):
                raise RuntimeFailure("archive_escapes", member.name)
        yield member


async def _download(url: str, out: Path) -> str:
    digest = hashlib.sha256()
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with out.open("wb") as fh:
                async for chunk in response.aiter_bytes(1 << 16):
                    digest.update(chunk)
                    fh.write(chunk)
    return digest.hexdigest()


async def ensure(name: str) -> Path:
    """The runtime's main binary, downloading and verifying it on first need."""
    if name not in PINS:
        raise RuntimeFailure("unknown_runtime", name)
    if not available():
        raise RuntimeFailure("unsupported_platform", f"{platform.system()} {platform.machine()}")
    lock = _locks.setdefault(name, asyncio.Lock())
    async with lock:
        if ready(name):
            return binary(name)
        pin = PINS[name]
        root().mkdir(parents=True, exist_ok=True)
        part = root() / f".{pin.name}-{pin.version}.tar.gz.part"
        try:
            got = await _download(pin.url, part)
            if got != pin.sha256:
                raise RuntimeFailure("checksum_mismatch", f"{pin.name} {pin.version}: {got}")
            staging = root() / f".{pin.name}-{pin.version}.staging"
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir()
            with tarfile.open(part, "r:gz") as archive:
                archive.extractall(staging, members=list(_safe_members(archive, staging)))  # noqa: S202 — members checked
            shutil.rmtree(home(name), ignore_errors=True)
            staging.rename(home(name))
        except httpx.HTTPError as exc:
            raise RuntimeFailure("download_failed", type(exc).__name__) from exc
        finally:
            part.unlink(missing_ok=True)
        if not ready(name):
            raise RuntimeFailure("archive_unexpected", f"{pin.name}: {pin.binaries} not found")
        logger.info("runtime %s %s ready", pin.name, pin.version)
        return binary(name)
