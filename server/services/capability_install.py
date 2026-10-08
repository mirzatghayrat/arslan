"""Installing a capability: pinned, checked, sandboxed (0.1.57 §5).

Called ONLY from the user's answer to a proposal card (P3) or the dossier's install button —
never from search results (the supply-chain line, test_capability_supply_chain). Every
install:

- reads the license at the source first (the repository's LICENSE file through GitHub, or a
  skill's own license file); not usable → refused before anything is downloaded;
- pins: a lock with hashes (pypi via uv, npm via Node) or a published checksum (mcpb) or a
  commit (skills), and records the checksum in the dossier;
- runs no package code while installing: wheels only (`--only-binary :all:`) for Python,
  `--ignore-scripts` for npm, so nothing executes before the sandbox exists;
- leaves the server switched OFF (`host_allowed` False): the first test decides (P3).

The server then starts under capability_sandbox: its own folder, the folders granted to it,
Arslan's runtimes read-only, and the network only when it needs a key for a service.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import httpx

from server.db import session as db_session
from server.db.models import CapabilitySource, MCPServer
from server.services import capability_runtime

logger = logging.getLogger(__name__)

STEP_TIMEOUT_S = 300
PYTHON_VERSION = "3.12"
_NAME = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/@-]{0,200}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,60}$")


class InstallFailure(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail[-800:]


def capabilities_root() -> Path:
    from server import config
    return config.data_dir() / "capabilities"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _run(argv: list[str], *, cwd: Path, env: dict) -> str:
    """One install step, bounded; its output tail goes into the failure."""
    proc = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd), env=env, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), STEP_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        raise InstallFailure("step_timeout", " ".join(argv[:3])) from None
    text = (out or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        raise InstallFailure("step_failed", f"{Path(argv[0]).name} {' '.join(argv[1:3])}: {text}")
    return text


def _base_env(extra: dict | None = None) -> dict:
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8"}
    return {**env, **(extra or {})}


# ── license at the source ────────────────────────────────────────────────────

async def source_license(repo: str | None) -> tuple[str | None, str | None]:
    """(SPDX, the file it was read from) for a repository: its LICENSE file at HEAD, read
    from raw.githubusercontent.com (not the API, which allows 60 calls an hour without a
    token) and recognised by its wording (skill_import.detect_license) — never metadata."""
    from server.services import skill_import
    if not repo or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return None, None
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for name in skill_import._LICENSE_NAMES:
            r = await client.get(f"https://raw.githubusercontent.com/{repo}/HEAD/{name}")
            if r.status_code == 200:
                return skill_import.detect_license(r.text), name
    return None, None


# ── per runtime ──────────────────────────────────────────────────────────────

def _console_script(venv: Path, identifier: str) -> str:
    """The package's own command: its console script named like the package, or its only one."""
    want = re.sub(r"[-_.]+", "-", identifier).lower()
    scripts: list[str] = []
    for ep in venv.glob("lib/python*/site-packages/*.dist-info/entry_points.txt"):
        # "excel_mcp_server-1.1.2.dist-info": drop the suffix first — its own "-" is the last one.
        dist = re.sub(r"[-_.]+", "-", ep.parent.name.removesuffix(".dist-info").rsplit("-", 1)[0]).lower()
        if dist != want:
            continue
        section = None
        for line in ep.read_text().splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line.strip("[]")
            elif section == "console_scripts" and "=" in line:
                scripts.append(line.split("=", 1)[0].strip())
    for name in scripts:
        if re.sub(r"[-_.]+", "-", name).lower() == want:
            return name
    if len(scripts) == 1:
        return scripts[0]
    raise InstallFailure("no_command", f"{identifier}: console scripts {scripts or 'none'}")


async def install_pypi(root: Path, identifier: str, version: str) -> dict:
    uv = await capability_runtime.ensure("uv")
    rt = capability_runtime.root()
    env = _base_env({"UV_CACHE_DIR": str(rt / "uv-cache"), "UV_PYTHON_INSTALL_DIR": str(rt / "python"),
                     "UV_NO_CONFIG": "1", "UV_PYTHON_PREFERENCE": "only-managed"})
    (root / "requirements.in").write_text(f"{identifier}=={version}\n")
    await _run([str(uv), "pip", "compile", "requirements.in", "--generate-hashes", "--only-binary", ":all:",
                "--python-version", PYTHON_VERSION, "-o", "requirements.lock", "--quiet"], cwd=root, env=env)
    await _run([str(uv), "venv", "venv", "--python", PYTHON_VERSION, "--quiet"], cwd=root, env=env)
    await _run([str(uv), "pip", "install", "--python", str(root / "venv" / "bin" / "python"), "--require-hashes",
                "--only-binary", ":all:", "-r", "requirements.lock", "--quiet"], cwd=root, env=env)
    script = _console_script(root / "venv", identifier)
    return {"command": str(root / "venv" / "bin" / script), "args": [],
            "lock_sha256": _sha256(root / "requirements.lock")}


async def install_npm(root: Path, identifier: str, version: str) -> dict:
    node = await capability_runtime.ensure("node")
    npm = capability_runtime.binary("node", "bin/npm")
    rt = capability_runtime.root()
    env = _base_env({"PATH": f"{node.parent}:/usr/bin:/bin", "npm_config_cache": str(rt / "npm-cache"),
                     "npm_config_ignore_scripts": "true", "npm_config_audit": "false", "npm_config_fund": "false",
                     "npm_config_update_notifier": "false", "HOME": str(root)})
    (root / "package.json").write_text(json.dumps({"name": "arslan-capability", "private": True}))
    await _run([str(npm), "install", f"{identifier}@{version}", "--package-lock-only", "--ignore-scripts",
                "--save-exact"], cwd=root, env=env)
    await _run([str(npm), "ci", "--ignore-scripts", "--omit=dev"], cwd=root, env=env)
    pkg_dir = root / "node_modules" / identifier
    manifest = json.loads((pkg_dir / "package.json").read_text())
    bins = manifest.get("bin")
    if isinstance(bins, str):
        entry = bins
    elif isinstance(bins, dict) and bins:
        short = identifier.rsplit("/", 1)[-1]
        entry = bins.get(short) or (next(iter(bins.values())) if len(bins) == 1 else None)
    else:
        entry = None
    if not entry:
        raise InstallFailure("no_command", f"{identifier}: bin {bins!r}")
    target = (pkg_dir / entry).resolve()
    if not target.is_relative_to(pkg_dir.resolve()):
        raise InstallFailure("no_command", "bin points outside the package")
    return {"command": str(node), "args": [str(target)], "lock_sha256": _sha256(root / "package-lock.json")}


def _safe_unzip(archive: Path, dest: Path) -> None:
    base = dest.resolve()
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(base):
                raise InstallFailure("archive_escapes", info.filename)
        z.extractall(dest)


async def install_mcpb(root: Path, url: str, sha256: str | None) -> dict:
    if not sha256:
        raise InstallFailure("no_checksum", "the registry gives no checksum for this bundle")
    part = root / "server.mcpb"
    got = await capability_runtime._download(url, part)
    if got != sha256.lower():
        raise InstallFailure("checksum_mismatch", got)
    bundle = root / "bundle"
    _safe_unzip(part, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text())
    server = manifest.get("server") or {}
    kind, entry = server.get("type"), server.get("entry_point")
    if not entry:
        raise InstallFailure("no_command", "manifest has no entry_point")
    target = (bundle / entry).resolve()
    if not target.is_relative_to(bundle.resolve()):
        raise InstallFailure("no_command", "entry point outside the bundle")
    if kind == "node":
        node = await capability_runtime.ensure("node")
        return {"command": str(node), "args": [str(target)], "lock_sha256": sha256.lower()}
    if kind == "binary":
        target.chmod(0o755)
        return {"command": str(target), "args": [], "lock_sha256": sha256.lower()}
    # Partial (0.1.57): a Python bundle needs its own interpreter setup; not run yet.
    raise InstallFailure("mcpb_unsupported", f"server type {kind!r}")


# ── the install ──────────────────────────────────────────────────────────────

_FOLDER_FORMATS = ("filepath", "directory", "dirpath", "path")


def start_arguments(package: dict, folders: list[str]) -> list[str]:
    """The registry's packageArguments as argv: fixed values as given; a named folder
    argument filled with the first folder the user granted; anything else that needs a
    value we do not have is left out (and if it was required, the install says so)."""
    argv: list[str] = []
    for arg in package.get("arguments") or []:
        value = arg.get("value")
        if value is None and arg.get("format") in _FOLDER_FORMATS and folders:
            value = folders[0]
        if value is None:
            if arg.get("isRequired"):
                raise InstallFailure("needs_argument", str(arg.get("name") or arg.get("type")))
            continue
        if not isinstance(value, str) or len(value) > 500:
            raise InstallFailure("bad_argument", str(arg.get("name")))
        if arg.get("type") == "named" and arg.get("name"):
            argv += [str(arg["name"]), value]
        else:
            argv.append(value)
    return argv


def _check_candidate(c: dict) -> None:
    if c.get("kind") != "mcp":
        raise InstallFailure("not_an_mcp_server")
    if c.get("not_here"):
        raise InstallFailure("not_here", c["not_here"])
    if c.get("runtime") not in ("uv", "node", "mcpb", "remote"):
        raise InstallFailure("no_runtime", str(c.get("runtime")))
    pkg = c.get("package") or {}
    if c["runtime"] == "mcpb" and not str(pkg.get("identifier") or "").startswith("https://"):
        raise InstallFailure("bad_package", "a bundle is downloaded over https only")
    if c["runtime"] in ("uv", "node"):
        if not _NAME.fullmatch(str(pkg.get("identifier") or "")) or not _VERSION.fullmatch(str(pkg.get("version") or "")):
            raise InstallFailure("bad_package", f"{pkg.get('identifier')!r} {pkg.get('version')!r}")


def grants_for(folders: list[str], needs: dict) -> dict:
    """What the server may touch (§5.3): existing folders the user named (real paths), and
    the network only when it needs a key for a service (a secret key means a remote API)."""
    real = []
    for f in folders or []:
        p = Path(os.path.realpath(os.path.expanduser(f)))
        if p.is_dir() and str(p) not in real and str(p) != "/":
            real.append(str(p))
    network = bool(needs.get("network")) or any(k.get("secret") for k in needs.get("keys") or [])
    return {"folders": real, "network": network}


async def install(candidate: dict, *, folders: list[str], keys: dict[str, str] | None = None,
                  owner_id: str = "local") -> CapabilitySource:
    """Install one MCP server candidate (as the search returned it). Returns its dossier row
    in state `installed` with the server registered and switched OFF, or `failed` with why."""
    _check_candidate(candidate)
    spdx, license_path = await source_license(candidate.get("repo"))
    from server.services.skill_import import _license_gate
    if candidate.get("runtime") != "remote" and _license_gate(spdx):
        raise InstallFailure("license", _license_gate(spdx) or "")
    source_id = uuid.uuid4().hex
    needs = candidate.get("needs") or {"keys": [], "network": None}
    grants = grants_for(folders, needs)
    row = CapabilitySource(
        id=source_id, owner_id=owner_id, kind="mcp", name=str(candidate.get("name"))[:120],
        candidate_id=str(candidate.get("id"))[:300], source_url=candidate.get("source_url"), repo=candidate.get("repo"),
        version=(candidate.get("package") or {}).get("version") or candidate.get("version"),
        license_spdx=spdx, license_path=license_path, stars=candidate.get("stars"),
        pushed_days=candidate.get("pushed_days"), checked_at=datetime.utcnow(), runtime=candidate.get("runtime"),
        needs=needs, grants=grants, state="proposed", created_at=datetime.utcnow())
    root = capabilities_root() / source_id
    try:
        if candidate["runtime"] == "remote":
            spec = {"transport": "http", "url": (candidate.get("remote") or {}).get("url"), "command": "", "args": []}
        else:
            root.mkdir(parents=True, exist_ok=True)
            pkg = candidate.get("package") or {}
            argv = start_arguments(pkg, grants["folders"])
            if candidate["runtime"] == "uv":
                spec = await install_pypi(root, pkg["identifier"], pkg["version"])
            elif candidate["runtime"] == "node":
                spec = await install_npm(root, pkg["identifier"], pkg["version"])
            else:
                spec = await install_mcpb(root, pkg["identifier"], pkg.get("file_sha256"))
            spec["args"] = [*spec.get("args", []), *argv]
            spec["transport"] = "stdio"
        row.lock_sha256 = spec.get("lock_sha256")
        sandbox = None if spec["transport"] == "http" else {
            "root": str(root), "folders": grants["folders"], "network": grants["network"],
            "read": [str(capability_runtime.root())]}
        async with db_session.AsyncSessionLocal() as db:
            server = MCPServer(label=row.name[:80], transport=spec["transport"], command=spec.get("command") or "",
                               args=spec.get("args") or [], url=spec.get("url"), status="registered",
                               host_allowed=False, sandbox=sandbox)
            from server import crypto
            server.env = crypto.encrypt(json.dumps(keys or {}))
            db.add(server)
            await db.flush()
            row.mcp_server_id, row.state, row.installed_at = server.id, "installed", datetime.utcnow()
            db.add(row)
            await db.commit()
        return row
    except (InstallFailure, capability_runtime.RuntimeFailure) as exc:
        row.state, row.error = "failed", f"{exc.code}: {getattr(exc, 'detail', '')}"[:1000]
        async with db_session.AsyncSessionLocal() as db:
            db.add(row)
            await db.commit()
        shutil.rmtree(root, ignore_errors=True)
        raise


def to_trash(path: Path) -> Path | None:
    """Move a capability's folder to the user's Trash (never deleted outright)."""
    if not path.exists():
        return None
    trash = Path.home() / ".Trash"
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / f"Arslan capability {path.name}"
    n = 1
    while target.exists():
        n += 1
        target = trash / f"Arslan capability {path.name} {n}"
    shutil.move(str(path), str(target))
    return target


async def remove(source_id: str) -> None:
    """Switch off and remove: the server row goes, the folder goes to the Trash."""
    from server.services import mcp_service
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(CapabilitySource, source_id)
        if row is None:
            raise InstallFailure("not_found")
        server_id = row.mcp_server_id
    if server_id:
        try:
            await mcp_service.delete_server(server_id)
        except Exception:  # noqa: BLE001 — already gone
            logger.info("capability %s: server %s already gone", source_id, server_id)
    to_trash(capabilities_root() / source_id)
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(CapabilitySource, source_id)
        row.state = "removed"
        await db.commit()
