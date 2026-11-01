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
remembered until the entry changes again, with no expiry (the user, 2026-11-01), so the same answer does not park it
again; another answer does, and a clean answer ends the keep (F4). The install's own start records the check the card just made, with this Arslan version (F5). Hand-
added servers have no Registry entry and are not checked. A newer version is not asked about here: the dossier's
update (the user's click in Capabilities, with no card) installs it beside the old one, and its own starts are
checked like any other.

**A stated limit** (the user, 2026-11-01; #604 review F3): a remote server is checked by the URL its Registry
entry writes, not by the host the SDK's redirects lead to, as mainstream MCP clients do. Neither this check nor the
card (#584) follows redirects.

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


def _seen(entry_ref: tuple[str, str], problem: str | None, names: dict | None) -> str:
    """One digest of the Registry's answer to the entry asked (name@version: #604 review of 7dcba02a), so a kept
    answer is recognised and another one, or the same answer about another entry, is not."""
    return hashlib.sha256(json.dumps([list(entry_ref), problem, names], sort_keys=True).encode()).hexdigest()


async def _ask(name: str, version: str):
    """The Registry's entry for that name at that version, or NO_ANSWER for anything else (#604 review F1): a non-200
    answer, a body that is not an object, a server that is another name or version, or packages or remotes that are
    not lists of objects. A body that is not JSON raises ValueError, which the caller takes as no answer too.

    `include_deleted=true` (#604 re-check 3; checked against the live Registry on 2026-11-01): without it, a deleted
    version answers 404 "Server not found", like a name that never existed; with it, a deleted version answers 200
    with its `deleted` mark, an active or deprecated one answers as before, and only an unknown name or version
    answers 404 (no answer here)."""
    from server.services import capability_search
    url = (f"{capability_search.REGISTRY}/v0/servers/{quote(name, safe='')}/versions/{quote(version, safe='')}"
           "?include_deleted=true")
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        r = await client.get(url)
    if r.status_code != 200:
        return NO_ANSWER
    body = r.json()
    srv = body.get("server", body) if isinstance(body, dict) else None
    if not isinstance(srv, dict) or srv.get("name") != name or srv.get("version") != version:
        return NO_ANSWER
    for key in ("packages", "remotes"):
        items = srv.get(key, [])            # #604 re-check 1: {}, "", 0 or false is not a list, so no answer
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            return NO_ANSWER
    return body


def _names_something(entry: dict, installed: dict) -> bool:
    """#604 re-check 1: whether a live entry names what the check compares, in the fields the parser reads: a remote
    with a URL for a remote install, or a package with its type and identifier. An entry that names none of it (a
    renamed field, no remotes) is no answer, not a change."""
    srv = entry.get("server", entry)
    if "url" in installed:
        return any(isinstance(r.get("url"), str) and r["url"] for r in srv.get("remotes", []))
    return any(isinstance(p.get("registryType"), str) and isinstance(p.get("identifier"), str) and p["identifier"]
               for p in srv.get("packages", []))


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


def _kept(check: dict) -> bool:
    """The user kept this very answer (its digest). It holds until the entry changes again (no expiry, the user
    2026-11-01); a clean answer ends it (F4)."""
    keep, seen = check.get("accepted"), check.get("seen")
    return isinstance(keep, dict) and isinstance(seen, str) and bool(seen) and keep.get("seen") == seen


def parked(source: CapabilitySource) -> dict | None:
    """What the source view shows of a server this check parked, so the page's row and its keep button need no
    rule of their own (#604 review F6): why, when the Registry was asked, what was installed, what the entry names
    now (None for a withdrawn one), `hidden`, how many characters that show nothing each side held before it was
    cleaned (#604 review L1: a name that differs only by one is a change, though both read the same), and `seen`,
    the digest a keep sends (`accept_source`). None when nothing is parked, or when the user kept this very
    answer."""
    check = (source.test or {}).get("registry_check") or {}
    if not check.get("problem") or _kept(check):
        return None
    installed = _installed(source.candidate or {})
    return {"why": check["problem"], "seen": check.get("seen"), "checked_at": check.get("at"),
            "installed": _shown(installed), "now": _shown(check.get("names")),
            "hidden": {"installed": discovery._hidden(installed), "now": discovery._hidden(check.get("names"))}}


def _shown(names) -> dict | None:
    """The Registry wrote these values, so they are cleaned as the card cleans a name (UNI1): no bidi override or
    zero-width character reaches the page, where it could make one name read as another."""
    from server.orchestrator import untrusted
    if not isinstance(names, dict):
        return None
    return {key: untrusted.clean_name(value, 512) if isinstance(value, str) else None for key, value in names.items()}


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
                     "seen": _seen(entry_ref, None, installed), "names": installed, "accepted": None}
            source.test = {**(source.test or {}), "registry_check": check}
            await db.commit()
        elif _due(check, now, version):
            try:
                entry = await _ask(*entry_ref)
                if entry is not NO_ANSWER:
                    from server.services import capability_search
                    if capability_search._deleted(entry):
                        problem, names = WITHDRAWN, None
                    elif not _names_something(entry, installed):
                        entry = NO_ANSWER
                    else:
                        names = _now_names(entry, installed)
                        problem = None if names == installed else CHANGED
            except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
                logger.info("mcp %s: the Registry did not answer the start check (%s)", server_id, type(exc).__name__)
                entry = NO_ANSWER
            if entry is not NO_ANSWER:
                seen = _seen(entry_ref, problem, names)
                check = {"at": now.isoformat() + "Z", "arslan": version, "problem": problem, "seen": seen,
                         "names": names, "accepted": check.get("accepted") if problem else None}    # F4
                source.test = {**(source.test or {}), "registry_check": check}
                await db.commit()
    if check.get("problem") and not _kept(check):
        raise SourceChanged(server_id, check["problem"])
