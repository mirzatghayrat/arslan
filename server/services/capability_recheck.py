"""An installed Registry server's entry, asked again before it starts (v0.1.64 CAP4a-3d; the user's Q3, 2026-10-31:
once a day per server, and on the first start after Arslan is updated).

The card showed one Registry entry: a package at one version, or a remote server's URL. Before a later start, when a
check is due, Arslan asks the Registry for that same version again:
- **withdrawn** (marked deleted, or gone): the server is parked;
- **changed** (that version now names another package, version or URL): parked;
- **the same:** it starts. The next check is due in a day, or after the next update of Arslan.

**The Registry not answering is no answer:** a server that passed its last check starts, a parked one stays parked,
and the next start asks again. **The user can keep a parked server** (`capability_dossier.accept_source`): that
answer is remembered, so the same answer does not park it again; another answer does. A just-installed server
counts as checked when it was installed. Hand-added servers have no Registry entry and are not checked; neither is
a newer version (the dossier's update installs it beside the old one, from a card the user answered).

The state lives in the capability source's `test` JSON (`registry_check`), like CAP5a's tool pin.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import CapabilitySource
from server.mcp import discovery

logger = logging.getLogger(__name__)

RECHECK = timedelta(days=1)
TIMEOUT_S = 10.0
WITHDRAWN, CHANGED = "withdrawn", "changed"
LINES = {WITHDRAWN: "its Registry entry was withdrawn since it was installed — see Capabilities",
         CHANGED: "its Registry entry no longer names what was installed — see Capabilities"}


class SourceChanged(discovery.Parked):
    def __init__(self, server_id: int, problem: str):
        super().__init__(server_id, LINES[problem])
        self.problem = problem


def _entry_of(cand: dict) -> tuple[str, str] | None:
    """The Registry name and version a card showed (`registry:<name>@<version>`)."""
    cid = str(cand.get("id") or "")
    if not cid.startswith("registry:") or "@" not in cid:
        return None
    name, _, version = cid.removeprefix("registry:").rpartition("@")
    return (name, version) if name and version else None


def _installed(cand: dict) -> dict:
    """What was installed from that entry: the package (type, name, version), or the remote URL."""
    if cand.get("runtime") == "remote":
        return {"url": (cand.get("remote") or {}).get("url")}
    pkg = cand.get("package") or {}
    return {"registry_type": pkg.get("registry_type"), "identifier": pkg.get("identifier"), "version": pkg.get("version")}


def _now_names(entry: dict, installed: dict) -> dict:
    """What the entry names now, in the same shape (the first remote, or the package of the installed type)."""
    srv = entry.get("server", entry)
    if "url" in installed:
        return {"url": ((srv.get("remotes") or [{}])[0] or {}).get("url")}
    pkg = next((p for p in srv.get("packages") or [] if p.get("registryType") == installed["registry_type"]), None) or {}
    return {"registry_type": pkg.get("registryType"), "identifier": pkg.get("identifier"),
            "version": pkg.get("version") or srv.get("version")}


def _seen(problem: str | None, names: dict | None) -> str:
    """One digest of the Registry's answer, so a kept answer is recognised and another one is not."""
    return hashlib.sha256(json.dumps([problem, names], sort_keys=True).encode()).hexdigest()


async def _ask(name: str, version: str) -> dict | None:
    """The entry for that version, or None when the Registry has none. Anything else raises."""
    from server.services import capability_search
    url = f"{capability_search.REGISTRY}/v0/servers/{quote(name, safe='')}/versions/{quote(version, safe='')}"
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        r = await client.get(url)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _due(check: dict, source: CapabilitySource, now: datetime, version: str) -> bool:
    if not check:                                   # never checked: due a day after the install's own check
        return source.checked_at is None or now - source.checked_at >= RECHECK
    try:
        at = datetime.fromisoformat(str(check.get("at")).removesuffix("Z"))
    except ValueError:
        return True
    return now - at >= RECHECK or check.get("arslan") != version


async def _source_for(db, server_id: int) -> CapabilitySource | None:
    return (await db.execute(select(CapabilitySource).where(
        CapabilitySource.mcp_server_id == server_id, CapabilitySource.kind == "mcp",
        CapabilitySource.state == "installed").order_by(CapabilitySource.created_at.desc()))).scalars().first()


async def before_start(server_id: int) -> None:
    """Raise SourceChanged when this server's Registry entry was withdrawn or changed and the user has not kept
    it. Asks the Registry only when a check is due."""
    from server import config
    async with db_session.AsyncSessionLocal() as db:
        source = await _source_for(db, server_id)
        entry_ref = _entry_of(source.candidate or {}) if source is not None else None
        if entry_ref is None:
            return
        check = dict((source.test or {}).get("registry_check") or {})
        now, version = datetime.utcnow(), str(config._app_version())
        if _due(check, source, now, version):
            installed = _installed(source.candidate)
            try:
                entry = await _ask(*entry_ref)
            except (httpx.HTTPError, ValueError) as exc:
                logger.info("mcp %s: the Registry did not answer the start check (%s)", server_id, type(exc).__name__)
                entry = False
            if entry is not False:
                from server.services import capability_search
                if entry is None or capability_search._deleted(entry):
                    problem, names = WITHDRAWN, None
                else:
                    names = _now_names(entry, installed)
                    problem = None if names == installed else CHANGED
                check = {"at": now.isoformat() + "Z", "arslan": version, "problem": problem,
                         "seen": _seen(problem, names), "names": names, "accepted": check.get("accepted")}
                source.test = {**(source.test or {}), "registry_check": check}
                await db.commit()
    if check.get("problem") and check.get("seen") != check.get("accepted"):
        raise SourceChanged(server_id, check["problem"])
