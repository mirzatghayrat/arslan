"""What Arslan installed, on the Capabilities page (0.1.57 §7): each capability's dossier, the
folders it may touch, updates, and removal.

Installing happens only from the card in a conversation (capability_flow). v0.1.64 CAP1a removed
the page's own search, install and "found for later" rail.
"""
from __future__ import annotations

import json
import logging

import httpx
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import CapabilitySource, MCPServer
from server.services import capability_flow, capability_install, capability_search

logger = logging.getLogger(__name__)


class DossierError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── dossiers ─────────────────────────────────────────────────────────────────

def view(row: CapabilitySource) -> dict:
    return {"id": row.id, "kind": row.kind, "name": row.name, "candidate_id": row.candidate_id,
            "source_url": row.source_url, "repo": row.repo, "version": row.version, "commit_sha": row.commit_sha,
            "artifact_sha256": row.artifact_sha256, "lock_sha256": row.lock_sha256,
            "license": {"spdx": row.license_spdx, "read_from": row.license_path},
            "stars": row.stars, "pushed_days": row.pushed_days,
            "checked_at": row.checked_at.isoformat() + "Z" if row.checked_at else None,
            "runtime": row.runtime, "needs": row.needs or {}, "grants": row.grants or {}, "scan": row.scan,
            "test": row.test, "files": row.files, "state": row.state, "error": row.error,
            "mcp_server_id": row.mcp_server_id, "skill_key": row.skill_key,
            "installed_at": row.installed_at.isoformat() + "Z" if row.installed_at else None}


async def sources(owner_id: str = "local") -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(CapabilitySource).where(
            CapabilitySource.owner_id == owner_id, CapabilitySource.state.in_(("installed", "failed")),
        ).order_by(CapabilitySource.created_at.desc()))).scalars().all()
    return [view(r) for r in rows]


async def source(source_id: str, owner_id: str = "local") -> CapabilitySource:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(CapabilitySource, source_id)
    if row is None or row.owner_id != owner_id or row.state == "removed":     # #499 second review 2
        raise DossierError("source_not_found")
    return row


async def set_folders(source_id: str, folders: list[str]) -> dict:
    """Change what an installed server may touch: the sandbox grants and a folder argument
    the server takes (e.g. --allow-dir). Takes effect at its next start: its session is dropped
    now and a fresh start scheduled in the background (0.1.61 ruling 3) — never awaited here."""
    from server.services import mcp_service
    row = await source(source_id)
    if row.kind != "mcp" or not row.mcp_server_id or row.runtime == "remote":
        raise DossierError("no_folders_here")
    grants = capability_install.grants_for(folders, row.needs or {})
    pkg = (row.candidate or {}).get("package") or {}
    async with db_session.AsyncSessionLocal() as db:
        server = await db.get(MCPServer, row.mcp_server_id)
        old_argv = capability_install.start_arguments(pkg, (row.grants or {}).get("folders") or [])
        base = list(server.args or [])[: len(server.args or []) - len(old_argv)] if old_argv else list(server.args or [])
        server.args = base + capability_install.start_arguments(pkg, grants["folders"])
        server.sandbox = {**(server.sandbox or {}), "folders": grants["folders"]}
        stored = await db.get(CapabilitySource, source_id)
        stored.grants = {**(stored.grants or {}), "folders": grants["folders"]}
        await db.commit()
    await mcp_service.restart_after_edit(row.mcp_server_id)     # restarted with the new grants
    return view(await source(source_id))


async def accept_tools(source_id: str, digest: str) -> dict:
    """CAP5a: the user read a server's tool change (its `test.tools_changed`) and accepts it: those tools become
    the pin, the hold ends, and the server starts again in the background, so its next listing is compared to
    them. `digest` names the change the user read: a change recorded since, or none, is refused, and nothing is
    pinned; so is a change too large to show whole (#577 review F2), which only a removal or a reinstall ends.
    It runs under the server's listing lock, so a listing's record and this accept never interleave."""
    from server.mcp import discovery
    from server.services import mcp_service
    row = await source(source_id)
    if row.kind != "mcp" or not row.mcp_server_id:
        raise DossierError("no_tool_change")
    async with discovery._write_locks.hold(row.mcp_server_id):
        async with db_session.AsyncSessionLocal() as db:
            stored = await db.get(CapabilitySource, source_id)
            test = dict(stored.test or {})
            change = test.get("tools_changed") or {}
            if not change:
                raise DossierError("no_tool_change")
            if not isinstance(digest, str) or digest != change.get("digest"):
                raise DossierError("tool_change_moved")
            if not change.get("reviewable", True):
                raise DossierError("too_long_to_review")
            test.pop("tools_changed")
            stored.test = {**test, "tools_pin": change["pin"]}
            await db.commit()
    await mcp_service.restart_after_edit(row.mcp_server_id)
    return view(await source(source_id))


async def accept_source(source_id: str, seen: str) -> dict:
    """CAP4a-3d: the user read why this server's Registry entry parked it (withdrawn, or changed) and keeps it:
    that answer (`seen`, its digest) is remembered, so the same answer does not park it again, and the server
    starts again in the background. Another answer since, or none, is refused."""
    from server.mcp import discovery
    from server.services import mcp_service
    row = await source(source_id)
    if row.kind != "mcp" or not row.mcp_server_id:
        raise DossierError("no_source_problem")
    async with discovery._write_locks.hold(row.mcp_server_id):     # never interleaved with a start's check
        async with db_session.AsyncSessionLocal() as db:
            stored = await db.get(CapabilitySource, source_id)
            check = dict((stored.test or {}).get("registry_check") or {})
            if not check.get("problem"):
                raise DossierError("no_source_problem")
            if not isinstance(seen, str) or seen != check.get("seen"):
                raise DossierError("source_answer_moved")
            stored.test = {**(stored.test or {}), "registry_check": {**check, "accepted": seen}}
            await db.commit()
    await mcp_service.restart_after_edit(row.mcp_server_id)
    return view(await source(source_id))


async def remove(source_id: str) -> None:
    row = await source(source_id)
    if row.kind == "skill":
        from server.db.models import SkillPack
        from server.services import capability_list
        # Only the skill this source installed: the key may since hold another skill, or name a seed
        # (#499 second review 2). Its files first, as capability_list.remove does (#499 review F3, F4).
        async with db_session.AsyncSessionLocal() as db:
            pack = await db.get(SkillPack, row.skill_key) if row.skill_key else None
        ours = pack is not None and pack.source_id == source_id
        if ours:
            try:
                capability_list.skill_to_trash(pack)
            except capability_list.NotRemovable as exc:            # its folder is a link (#499 recheck 1)
                raise DossierError("not_removable") from exc
        elif pack is None and capability_list.safe_skill_key(row.skill_key):
            # Nothing holds the key: the folder is this source's leftover, which run_python could still load
            # (#499 recheck nit). to_trash moves a link itself.
            from server import config
            capability_install.to_trash(config.data_dir() / "skill_scripts" / row.skill_key)
        async with db_session.AsyncSessionLocal() as db:
            pack = await db.get(SkillPack, row.skill_key) if ours else None
            if pack is not None:
                await db.delete(pack)
            stored = await db.get(CapabilitySource, source_id)
            stored.state = "removed"
            await db.commit()
        return
    await capability_install.remove(source_id)


# ── updates (§7) ─────────────────────────────────────────────────────────────

def _registry_name(row: CapabilitySource) -> str | None:
    cid = row.candidate_id or ""
    return cid.split(":", 1)[1].rsplit("@", 1)[0] if cid.startswith("registry:") else None


async def check_update(source_id: str) -> dict:
    """Is there a newer version in the registry, and what changed (§7: shown first)."""
    row = await source(source_id)
    name = _registry_name(row)
    if not name:
        return {"current": row.version, "latest": row.version, "newer": False, "reason": "not_from_registry"}
    async with httpx.AsyncClient(timeout=capability_search.TIMEOUT_S) as client:
        r = await client.get(f"{capability_search.REGISTRY}/v0/servers/{name.replace('/', '%2F')}/versions/latest")
    if r.status_code != 200:
        return {"current": row.version, "latest": None, "newer": False, "reason": "registry_unavailable"}
    latest = capability_search.from_registry(r.json())
    newer = capability_search._version_key(latest.version) > capability_search._version_key(row.version)
    compare = (f"https://github.com/{row.repo}/compare/v{row.version}...v{latest.version}"
               if newer and row.repo else None)
    return {"current": row.version, "latest": latest.version, "newer": newer, "compare_url": compare,
            "candidate": latest.view() if newer else None}


async def update(source_id: str) -> dict:
    """Install the newer version beside the old one (same folders, same keys); only when it
    passes scan and test is the old one removed — otherwise the old one stays on."""
    from server import crypto
    row = await source(source_id)
    info = await check_update(source_id)
    if not info.get("newer"):
        raise DossierError("no_newer_version")
    cand = info["candidate"]
    cand["license"] = (await check_candidate_license(cand))
    problem = capability_flow.installable(cand)
    if problem:
        raise DossierError(problem)
    keys = {}
    if row.mcp_server_id:
        async with db_session.AsyncSessionLocal() as db:
            server = await db.get(MCPServer, row.mcp_server_id)
            if server is not None and server.env:
                try:
                    keys = json.loads(crypto.decrypt(server.env))
                except Exception:  # noqa: BLE001 — keys unreadable: the new one asks again on the page
                    keys = {}
    result = await capability_flow.install_mcp(cand, folders=(row.grants or {}).get("folders") or [], keys=keys)
    if result["state"] == "on":
        await capability_install.remove(source_id)
    return result


async def check_candidate_license(cand: dict) -> dict:
    spdx, path = await capability_install.source_license(cand.get("repo"))
    return {"spdx": spdx, "read_from": path,
            "verdict": capability_search.license_verdict(spdx, proprietary=bool(path) and spdx is None)}
