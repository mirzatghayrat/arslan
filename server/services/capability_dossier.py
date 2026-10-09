"""The Capabilities page's side of the loop (0.1.57 §4, §7, §8): what Arslan found for later,
each capability's dossier, installing from the page, the folders it may touch, updates, and
using a candidate in a project.

Installing from the page is the user naming the source (a click on that candidate's dossier),
so it goes through the same install → scan → test → switch-on as the in-chat card. A page
candidate must be one the page's own search returned (kept server-side under PAGE).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import CapabilityFind, CapabilitySource, MCPServer
from server.services import capability_flow, capability_install, capability_search

logger = logging.getLogger(__name__)

PAGE = "capabilities-page"          # the "conversation" the page's searches are remembered under
FIND_DAYS = 30


class DossierError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── what Arslan found ────────────────────────────────────────────────────────

def _find(row: CapabilityFind) -> dict:
    return {"id": row.id, "need": row.need, "why": row.why, "conversation_id": row.conversation_id,
            "project_id": row.project_id, "level_id": row.level_id, "candidate": row.candidate,
            "created_at": row.created_at.isoformat() + "Z"}


async def finds(owner_id: str = "local") -> list[dict]:
    """Open finds of the last 30 days, newest first; one per candidate."""
    since = datetime.utcnow() - timedelta(days=FIND_DAYS)
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(CapabilityFind).where(
            CapabilityFind.owner_id == owner_id, CapabilityFind.state == "open", CapabilityFind.created_at >= since,
        ).order_by(CapabilityFind.created_at.desc()).limit(60))).scalars().all()
    out, seen = [], set()
    for row in rows:
        key = (row.candidate or {}).get("id")
        if key in seen:
            continue
        seen.add(key)
        capability_search.remember(PAGE, {"candidates": [row.candidate]})   # installable from the page
        out.append(_find(row))
    return out[:30]


async def dismiss(find_id: str, owner_id: str = "local") -> None:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(CapabilityFind, find_id)
        if row is None or row.owner_id != owner_id:
            raise DossierError("find_not_found")
        row.state = "dismissed"
        await db.commit()


async def _mark_installed(candidate_id: str, owner_id: str) -> None:
    async with db_session.AsyncSessionLocal() as db:
        for row in (await db.execute(select(CapabilityFind).where(
                CapabilityFind.owner_id == owner_id, CapabilityFind.state == "open"))).scalars().all():
            if (row.candidate or {}).get("id") == candidate_id:
                row.state = "installed"
        await db.commit()


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
    if row is None or row.owner_id != owner_id:
        raise DossierError("source_not_found")
    return row


async def check(candidate_id: str) -> dict:
    """A candidate's dossier before install (§7): the license read from the source file
    itself (not the search's reading), and what it would need."""
    cand = capability_search.seen(PAGE, candidate_id)
    if cand is None:
        raise DossierError("unknown_candidate")
    if cand["kind"] == "skill" and cand.get("source") == "library":
        verified = cand["license"]                      # read from the skill's own file at its commit
    else:
        spdx, path = await capability_install.source_license(cand.get("repo"))
        verified = {"spdx": spdx, "read_from": path,
                    "verdict": capability_search.license_verdict(spdx, proprietary=bool(path) and spdx is None)}
        cand = {**cand, "license": verified}
        capability_search.remember(PAGE, {"candidates": [cand]})
    return {"candidate": cand, "installable": capability_flow.installable(cand) is None,
            "why_not": capability_flow.installable(cand)}


async def install(candidate_id: str, *, folders: list[str], keys: dict, owner_id: str = "local") -> dict:
    """"加进能力库" on a dossier: the same install → scan → test → switch-on as the card."""
    cand = capability_search.seen(PAGE, candidate_id)
    if cand is None:
        raise DossierError("unknown_candidate")
    problem = capability_flow.installable(cand)
    if problem:
        raise DossierError(problem)
    if cand["kind"] == "mcp":
        result = await capability_flow.install_mcp(cand, folders=folders, keys=keys)
    else:
        result = await capability_flow.install_skill(cand)
    if result["state"] == "on":
        await _mark_installed(candidate_id, owner_id)
    return result


async def set_folders(source_id: str, folders: list[str]) -> dict:
    """Change what an installed server may touch: the sandbox grants and a folder argument
    the server takes (e.g. --allow-dir). Takes effect at its next start (restarted now)."""
    from server.mcp.session import manager
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
    try:
        await manager._drop(row.mcp_server_id)
    except Exception:  # noqa: BLE001 — not running
        pass
    return view(await source(source_id))


async def remove(source_id: str) -> None:
    row = await source(source_id)
    if row.kind == "skill":
        from server import config
        from server.db.models import SkillPack
        async with db_session.AsyncSessionLocal() as db:
            pack = await db.get(SkillPack, row.skill_key) if row.skill_key else None
            if pack is not None:
                await db.delete(pack)
            stored = await db.get(CapabilitySource, source_id)
            stored.state = "removed"
            await db.commit()
        if row.skill_key:
            capability_install.to_trash(config.data_dir() / "skill_scripts" / row.skill_key)
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


# ── using a candidate in a project (§8) ──────────────────────────────────────

async def as_material(project_id: str, candidate_id: str, owner_id: str = "local") -> dict:
    """"当资料": its description and README go into the project's materials (its first
    collection, made if it has none). Reference data for Arslan; nothing is installed."""
    from server.db.models import Collection, Project
    from server.services import ingest
    cand = capability_search.seen(PAGE, candidate_id)
    if cand is None:
        raise DossierError("unknown_candidate")
    readme = ""
    if cand.get("repo"):
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for name in ("README.md", "readme.md", "README"):
                r = await client.get(f"https://raw.githubusercontent.com/{cand['repo']}/HEAD/{name}")
                if r.status_code == 200:
                    readme = r.text[:12000]
                    break
    async with db_session.AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        if project is None or project.owner_id != owner_id:
            raise DossierError("project_not_found")
        ids = list(project.collection_ids or [])
        collection_id = ids[0] if ids else None
        if collection_id is None:
            col = Collection(name=f"{project.name} · materials"[:100], description="Added from Capabilities")
            db.add(col)
            await db.flush()
            collection_id = col.id
            # Not a project edit: projects.version (which pins running tasks) is left alone.
            project.collection_ids = [collection_id]
        await db.commit()
    text = f"{cand['name']} — {cand.get('summary') or ''}\nSource: {cand.get('source_url') or ''}\n" \
           f"License: {(cand.get('license') or {}).get('spdx')}\n\n{readme}"
    chunks = await ingest.ingest_text(None, f"{cand['name']} ({cand.get('source_url') or 'capability'})", text,
                                      collection_id=collection_id)
    return {"collection_id": collection_id, "chunks": chunks}
