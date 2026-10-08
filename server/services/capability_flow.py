"""Ask → install → scan → test → switch on (0.1.57 §3, §6).

`propose` is what the model's `propose_capability` tool does. It may only name a candidate
this conversation was SHOWN by `find_capability` (capability_search.seen): the card is built
from that search result on the server, never from the model's words. Nothing installs unless
the user approves the card in the Arslan window that asked; a background job, or a turn with
nobody to ask, records the find for the Capabilities page instead (§3.2, §4).

After approval: install pinned and switched off (capability_install / skill_import at a
commit), scan what came in (capability_scan — a high finding removes it again), test once
(an MCP server must start in its sandbox and list at least one tool), and only then switch
it on. The tool result tells the model it can retry the step; the tool loop re-reads its
tools so the new ones are callable in the same turn.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from server.db import session as db_session
from server.db.models import CapabilityFind, CapabilitySource, MCPServer, SkillPack
from server.services import capability_install, capability_runtime, capability_scan, capability_search

logger = logging.getLogger(__name__)

TEST_TIMEOUT_S = 90


def installable(c: dict) -> str | None:
    """Why this candidate cannot be offered for install, or None."""
    if c.get("license", {}).get("verdict") != "usable":
        return "license_not_usable"
    if c.get("not_here"):
        return c["not_here"]
    if c.get("kind") == "mcp":
        return None if c.get("runtime") in ("uv", "node", "mcpb", "remote") else "no_runtime"
    if c.get("kind") == "skill":
        return None if c.get("repo") and c.get("path") else "pick_a_skill_in_the_repository"
    return "not_a_capability"


def _folders(raw) -> list[str]:
    """At most three, as text; grants_for keeps only real, existing folders (never "/")."""
    return [str(f)[:500] for f in (raw if isinstance(raw, list) else [])[:3]]


def card_for(c: dict, *, why: str, retry: str, folders: list[str]) -> dict:
    """What the card shows (board Capability-Propose), from the search result."""
    needs = c.get("needs") or {"keys": [], "network": None}
    grants = capability_install.grants_for(folders, needs)
    runtime = c.get("runtime")
    download = runtime in ("uv", "node") and not capability_runtime.ready(runtime)
    return {
        "kind": c["kind"], "name": c["name"], "summary": c.get("summary") or "", "source_url": c.get("source_url"),
        "repo": c.get("repo"), "version": (c.get("package") or {}).get("version") or c.get("version"),
        "license": {"spdx": c["license"]["spdx"], "read_from": c["license"]["read_from"]},
        "stars": c.get("stars"), "pushed_days": c.get("pushed_days"), "runtime": runtime,
        "runtime_download": ({"name": runtime, "size_mb": capability_runtime.PINS[runtime].size_mb} if download else None),
        "remote_host": (c.get("remote") or {}).get("url"), "network": grants["network"] if c["kind"] == "mcp" else False,
        "folders": grants["folders"] if c["kind"] == "mcp" else [],
        "keys": [k for k in needs.get("keys") or [] if k.get("required") or k.get("secret")][:6],
        "why": why[:300], "retry": retry[:300],
    }


async def record_find(c: dict, *, need: str, why: str, conversation_id: str | None,
                      project_id: str | None = None, level_id: str | None = None, owner_id: str = "local") -> str:
    """§4: kept for the Capabilities page ("Arslan 找到的"). Never a notification."""
    async with db_session.AsyncSessionLocal() as db:
        row = CapabilityFind(id=uuid.uuid4().hex, owner_id=owner_id, need=(need or c.get("name") or "")[:300], why=why,
                             conversation_id=conversation_id, project_id=project_id, level_id=level_id,
                             candidate=c, state="open", created_at=datetime.utcnow())
        db.add(row)
        await db.commit()
        return row.id


async def _source(source_id: str) -> CapabilitySource:
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(CapabilitySource, source_id)


async def _update(source_id: str, **fields) -> None:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(CapabilitySource, source_id)
        for key, value in fields.items():
            setattr(row, key, value)
        await db.commit()


async def test_mcp(source_id: str) -> dict:
    """Start it in its sandbox and list its tools; on success switch it on."""
    from server.mcp.discovery import connect_and_discover
    row = await _source(source_id)
    try:
        tools = await asyncio.wait_for(connect_and_discover(row.mcp_server_id), TEST_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — a failed start is the test's answer
        detail = getattr(exc, "detail", None) or str(exc)
        return {"ok": False, "stage": "start", "detail": detail[-400:] or type(exc).__name__,
                "at": datetime.utcnow().isoformat() + "Z"}
    names = [t["name"] for t in tools]
    if not names:
        return {"ok": False, "stage": "tools", "detail": "started, but listed no tools",
                "at": datetime.utcnow().isoformat() + "Z"}
    async with db_session.AsyncSessionLocal() as db:
        server = await db.get(MCPServer, row.mcp_server_id)
        server.host_allowed = True
        await db.commit()
    return {"ok": True, "tools": names[:60], "at": datetime.utcnow().isoformat() + "Z"}


async def install_mcp(c: dict, *, folders: list[str], keys: dict) -> dict:
    try:
        row = await capability_install.install(c, folders=folders, keys=keys)
    except (capability_install.InstallFailure, capability_runtime.RuntimeFailure) as exc:
        return {"state": "failed", "stage": "install", "code": exc.code, "detail": getattr(exc, "detail", "")[-400:]}
    if row.runtime != "remote":
        scan = await asyncio.to_thread(capability_scan.scan_install, capability_install.capabilities_root() / row.id)
        await _update(row.id, scan=scan)
        if scan["level"] == "blocked":
            await capability_install.remove(row.id)
            await _update(row.id, state="failed", error="scan: " + ", ".join(f["rule"] for f in scan["findings"]
                                                                              if f["level"] == "high"))
            return {"state": "blocked", "source_id": row.id, "scan": scan}
    else:
        scan = None
    test = await test_mcp(row.id)
    await _update(row.id, test=test, **({} if test["ok"] else {"state": "failed", "error": f"test: {test['stage']}"}))
    if not test["ok"]:
        return {"state": "failed", "stage": "test", "source_id": row.id, "detail": test["detail"]}
    return {"state": "on", "source_id": row.id, "tools": test["tools"], "scan": scan}


async def install_skill(c: dict, owner_id: str = "local") -> dict:
    from server import config
    from server.services import skill_import
    sha = c.get("version") if c.get("source") == "library" else None
    try:
        out = await skill_import.import_skill(f"{c['repo']}@{sha}" if sha else c["repo"], c["path"])
    except ValueError as exc:
        return {"state": "failed", "stage": "install", "code": "skill_import", "detail": str(exc)[:400]}
    key = out["key"]
    folder = config.data_dir() / "skill_scripts" / key
    read = lambda sub, exts: {p.name: p.read_text("utf-8", errors="replace")  # noqa: E731
                              for p in (folder / sub if sub else folder).glob("*") if p.suffix in exts}
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
        body = pack.body or ""
    scan = capability_scan.scan_skill(body, read("", (".py",)), read("references", (".md", ".txt")))
    source_id = uuid.uuid4().hex
    async with db_session.AsyncSessionLocal() as db:
        pack = await db.get(SkillPack, key)
        state = "installed"
        if scan["level"] == "blocked":
            await db.delete(pack)
            state = "failed"
        else:
            pack.source_id = source_id
        db.add(CapabilitySource(
            id=source_id, owner_id=owner_id, kind="skill", name=out["name"][:120], candidate_id=c["id"][:300],
            source_url=c.get("source_url"), repo=c.get("repo"), version=out["commit"][:12], commit_sha=out["commit"],
            license_spdx=out["license"], license_path=out.get("license_source"), stars=c.get("stars"),
            pushed_days=c.get("pushed_days"), checked_at=datetime.utcnow(), runtime="skill", needs={}, grants={},
            scan=scan, test={"ok": state == "installed", "stage": "scan", "at": datetime.utcnow().isoformat() + "Z"},
            files=out["files"], state=state, skill_key=key if state == "installed" else None,
            error=None if state == "installed" else "scan", created_at=datetime.utcnow(),
            installed_at=datetime.utcnow() if state == "installed" else None))
        await db.commit()
    if state != "installed":
        capability_install.to_trash(folder)
        return {"state": "blocked", "source_id": source_id, "scan": scan}
    return {"state": "on", "source_id": source_id, "skill": key, "scan": scan}


async def propose(args: dict, *, conversation_id: str | None, ask, emit) -> dict:
    """The model's `propose_capability`. Returns the tool result (and `refresh: True` when
    a new capability is on, so the loop re-reads its tools)."""
    cand = capability_search.seen(conversation_id, str(args.get("candidate_id") or ""))
    if cand is None:
        return {"ok": False, "error": "unknown candidate: call find_capability first and use one of its ids"}
    problem = installable(cand)
    if problem:
        return {"ok": False, "error": f"cannot be added: {problem}"}
    why = str(args.get("why") or "").strip()
    retry = str(args.get("retry") or "").strip()
    folders = _folders(args.get("folders"))
    card = card_for(cand, why=why, retry=retry, folders=folders)
    if ask is None:
        await record_find(cand, need=why, why="job", conversation_id=conversation_id)
        return {"ok": False, "recorded": True,
                "note": "Nobody to ask here (a background job). Saved on the Capabilities page under "
                        "'Arslan found' for the user; say so in your answer."}
    decision = await ask(card)
    if not decision.get("approved"):
        from server.services import approvals
        await record_find(cand, need=why, why="declined", conversation_id=conversation_id)
        outcome = approvals.LAST_OUTCOME.get() or "declined"
        return {"ok": False, "declined": True, "note": f"The user did not add it ({outcome}). Do the task another "
                                                        "way or say what is missing; do not propose it again now."}
    if cand["kind"] == "mcp":
        result = await install_mcp(cand, folders=decision.get("folders") or [], keys=decision.get("keys") or {})
    else:
        result = await install_skill(cand)
    emit({"type": "capability_result", "call_id": decision.get("call_id"), **{k: v for k, v in result.items()
                                                                            if k in ("state", "source_id", "stage",
                                                                                     "code", "detail")},
          "name": cand["name"], "tools": len(result.get("tools") or [])})
    if result["state"] == "on":
        what = (f"its tools: {', '.join(result['tools'][:20])}" if cand["kind"] == "mcp"
                else f"the skill '{result['skill']}' (read it with read_skill)")
        return {"ok": True, "installed": cand["name"], "refresh": True,
                "note": f"Installed, tested and switched on — {what}. Retry the step that failed now."}
    if result["state"] == "blocked":
        rules = ", ".join(f["rule"] for f in result["scan"]["findings"] if f["level"] == "high")
        return {"ok": False, "error": f"the scan found dangerous patterns ({rules}); it was removed again"}
    return {"ok": False, "error": f"it did not pass ({result.get('stage')}: {result.get('code') or ''} "
                                  f"{result.get('detail') or ''})".strip(), "note": "It stays off."}
