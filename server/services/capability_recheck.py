"""An installed Registry server's entry, asked again before it starts (v0.1.64 CAP4a-3d; the user's Q3, 2026-10-31:
once a day per server, and on the first start after Arslan is updated).

The card showed one Registry entry: a package at one version, or a remote server's URL. Before a later start, when a
check is due, Arslan asks the Registry for that same version again:
- **withdrawn** (that entry marked deleted): the server is parked;
- **changed** (that version now names another package, version or URL): parked;
- **the same:** it starts. The next check is due in a day, or at the first start after Arslan is updated. A parked
  server whose entry comes back the same starts again by itself: the code it runs never changed.

**Only the entry asked for is an answer** (#604 review F1): a 200 whose body is that name at that version. A 404
from anywhere (a moved route answers 404 too), an error, a body that is not JSON or not an object, or an entry for
another name or version is no answer. **No answer decides nothing:** a server that passed its last check starts, a
parked one stays parked, and the next start asks again, as installed npm and PyPI packages keep running while their
registry is down. **The user can keep a parked server** (`capability_dossier.accept_source`): that answer is
remembered for `KEEP_FOR`, so the same answer does not park it again; another answer does, and a clean answer ends
the keep (F4). The install's own start records the check the card just made, with this Arslan version (F5). Hand-
added servers have no Registry entry and are not checked. A newer version is not asked about here: the dossier's
update (the user's click in Capabilities, with no card) installs it beside the old one, and its own starts are
checked like any other.

The state lives in the capability source's `test` JSON (`registry_check`), like CAP5a's tool pin.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from server.db import session as db_session
from server.db.models import CapabilitySource
from server.mcp import discovery

logger = logging.getLogger(__name__)

RECHECK = timedelta(days=1)
#: How long the user's keep of one answer holds (#604 review F4); then the same answer parks the server again.
KEEP_FOR = timedelta(days=30)
TIMEOUT_S = 10.0
#: What `_ask` returns for anything that is not the entry asked for (#604 review F1).
NO_ANSWER = object()
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


async def _ask(name: str, version: str):
    """The Registry's entry for that name at that version, or NO_ANSWER for anything else (#604 review F1): a non-200
    answer, a body that is not an object, a server that is another name or version, or packages or remotes that are
    not lists of objects. A body that is not JSON raises ValueError, which the caller takes as no answer too."""
    from server.services import capability_search
    url = f"{capability_search.REGISTRY}/v0/servers/{quote(name, safe='')}/versions/{quote(version, safe='')}"
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        r = await client.get(url)
    if r.status_code != 200:
        return NO_ANSWER
    body = r.json()
    srv = body.get("server", body) if isinstance(body, dict) else None
    if not isinstance(srv, dict) or srv.get("name") != name or srv.get("version") != version:
        return NO_ANSWER
    for key in ("packages", "remotes"):
        items = srv.get(key) or []
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            return NO_ANSWER
    return body


def _when(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).removesuffix("Z"))
    except ValueError:
        return None


def _due(check: dict, now: datetime, version: str) -> bool:
    """A day after the last check, at the first start after an update, or when the last check is dated in the
    future (a clock set back since: #604 review F5)."""
    at = _when(check.get("at"))
    return at is None or at > now or now - at >= RECHECK or check.get("arslan") != version


def _just_installed(source: CapabilitySource, now: datetime) -> bool:
    """The install's own start: the card read this entry within the day, and no check is recorded yet."""
    return source.checked_at is not None and source.checked_at <= now and now - source.checked_at < RECHECK


def _kept(check: dict, now: datetime) -> bool:
    """The user kept this very answer (its digest), within `KEEP_FOR`."""
    keep = check.get("accepted")
    at = _when(keep.get("at")) if isinstance(keep, dict) else None
    return (at is not None and keep.get("seen") == check.get("seen") and at <= now and now - at < KEEP_FOR)


async def before_start(server_id: int) -> None:
    """Raise SourceChanged when this server's Registry entry was withdrawn or changed and the user has not kept
    it. Asks the Registry only when a check is due."""
    from server import config
    async with db_session.AsyncSessionLocal() as db:
        # #604 review F2: the same sources CAP5a pins (`discovery._source_of`): installed, or kept after a failed
        # test (the user can switch one on), and never a server added by hand on a reused number.
        source = await discovery._source_of(db, server_id)
        entry_ref = _entry_of(source.candidate or {}) if source is not None else None
        if entry_ref is None:
            return
        check = dict((source.test or {}).get("registry_check") or {})
        now, version = datetime.utcnow(), str(config._app_version())
        installed = _installed(source.candidate)
        if not check and _just_installed(source, now):
            check = {"at": source.checked_at.isoformat() + "Z", "arslan": version, "problem": None,
                     "seen": _seen(None, installed), "names": installed, "accepted": None}
            source.test = {**(source.test or {}), "registry_check": check}
            await db.commit()
        elif _due(check, now, version):
            try:
                entry = await _ask(*entry_ref)
                if entry is not NO_ANSWER:
                    from server.services import capability_search
                    if capability_search._deleted(entry):
                        problem, names = WITHDRAWN, None
                    else:
                        names = _now_names(entry, installed)
                        problem = None if names == installed else CHANGED
            except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
                logger.info("mcp %s: the Registry did not answer the start check (%s)", server_id, type(exc).__name__)
                entry = NO_ANSWER
            if entry is not NO_ANSWER:
                seen = _seen(problem, names)
                check = {"at": now.isoformat() + "Z", "arslan": version, "problem": problem, "seen": seen,
                         "names": names, "accepted": check.get("accepted") if problem else None}    # F4
                source.test = {**(source.test or {}), "registry_check": check}
                await db.commit()
    if check.get("problem") and not _kept(check, now):
        raise SourceChanged(server_id, check["problem"])
