"""Known vulnerabilities in what an install card would install (v0.1.64 CAP9; the CAP card, "CAP9 OSV.dev"). In
CAP4's slot between the lock and the card, every package in the lock (the one being installed and each of its
dependencies) is asked about in one OSV.dev batch query, and the card shows what OSV knows.

- **What is sent:** each locked package's name, ecosystem (PyPI or npm) and version, nothing else: nothing about
  the user or the conversation. An npm alias (`"innocent-name": "npm:event-stream@3.3.6"`) is asked by its real
  name, the one its lock entry names (#661 review F1). A lock with no packages is not checked (F3). One `POST /v1/querybatch` (at most QUERIES_MAX packages), then `GET /v1/vulns/{id}`
  for each advisory it names (at most LOOKUPS_MAX, the package itself first), for its severity, summary and fixed
  versions (at most FIXED_MAX listed). All of it within DEADLINE_S. A result's `next_page_token` (a package with
  more than a page of advisories) is not followed: the answer says it is incomplete.
- **One advisory, several ids:** OSV lists one advisory under its GitHub id and, for PyPI, its PyPA id as well
  (PYSEC-2019-217 aliases GHSA-462w-v97r-4m45). Records of one package that name each other in
  `aliases` count once, under the GitHub id. The severity is GitHub's word (`database_specific.severity`), the
  worst of the group; a group with none is UNKNOWN. CVSS vectors are not scored here.
- **The package itself leads:** `own` lists its advisories, `deps` each dependency that has any.
- **Not checked is never "none known":** OSV unreachable, an error status or a redirect, a body past MAX_BYTES or
  not the shape asked for, or DEADLINE_S passed: `{"state": "not_checked"}`, and the card says so. A single record
  that does not answer still counts, as UNKNOWN and `loaded: false`, and the answer is incomplete.
- **Fixed versions** are only the ones above the installed version, from version ranges (never a GIT range's
  commit); none is listed when none is above it, or when a version does not read as one.
- **Not asked:** a remote server (nothing is installed here), an MCP bundle (no ecosystem OSV knows) and a skill
  (it names no packages): `{"state": "skipped", "why": …}`.
- **What the card does with a hit is the user's question 5** (2026-11-02, "as drawn"): it warns and nothing is
  refused here; the card makes "Don't install" the button that leads and has focus, and ⌘⏎ does not install.

OSV's words are outside text on the card: an id must look like one before it is put in a URL or shown, and
summaries and versions are cleaned as a card name is (UNI1's `clean_name`). An id can hold a colon (Red Hat's
`RHSA-2023:1234`), so the page builds an advisory's link from a fixed osv.dev prefix, never from the id alone.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import quote

import httpx

from arslan.aio import within
from server.orchestrator import untrusted

logger = logging.getLogger(__name__)

OSV = "https://api.osv.dev"
DEADLINE_S = 20.0
#: OSV's own limit for one batch query.
QUERIES_MAX = 1000
#: Records looked up for their severity; the rest still count, as UNKNOWN.
LOOKUPS_MAX = 40
#: Advisories listed per package, and dependencies listed; `count` covers all of them.
SHOWN_MAX = 10
SUMMARY_MAX = 200
FIXED_MAX = 5
MAX_BYTES = {"batch": 4 * 1024 * 1024, "vuln": 512 * 1024}
ECOSYSTEM = {"uv": "PyPI", "node": "npm"}
SEVERITY = ("UNKNOWN", "LOW", "MODERATE", "HIGH", "CRITICAL")           # worst last
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
NOT_CHECKED = {"state": "not_checked", "why": "osv_did_not_answer"}


class ResponseTooLarge(ValueError):
    """An OSV answer past `MAX_BYTES`."""


def _name(ecosystem: str, name: str) -> str:
    """A package name as the ecosystem compares it: PyPI's normalized form (PEP 503); npm's as written."""
    return re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "PyPI" else name


async def _json(client: httpx.AsyncClient, method: str, url: str, kind: str, body: dict | None = None):
    """OSV's JSON answer, at most `MAX_BYTES[kind]`. A redirect is not followed: it is an error status here."""
    async with client.stream(method, url, json=body) as r:
        r.raise_for_status()
        got = bytearray()
        async for chunk in r.aiter_bytes():
            got += chunk
            if len(got) > MAX_BYTES[kind]:
                raise ResponseTooLarge(f"over {MAX_BYTES[kind]} bytes")
        try:
            return json.loads(bytes(got))
        except RecursionError as exc:           # #661 review F2: `[[[…]]]` under the cap is no answer, not a crash
            raise ValueError("nested too deep") from exc


def _hits(answer, asked: int) -> tuple[list[list[str]], bool]:
    """The ids the batch names for each package asked, and whether every page came back. Anything else than one
    result object per package, each with a list of vulns whose ids look like ids, is no answer (ValueError)."""
    results = answer.get("results") if isinstance(answer, dict) else None
    if not isinstance(results, list) or len(results) != asked:
        raise ValueError("not the batch asked for")
    hits, complete = [], True
    for result in results:
        vulns = result.get("vulns", []) if isinstance(result, dict) else None
        if not isinstance(vulns, list) or not all(isinstance(v, dict) for v in vulns):
            raise ValueError("a result that is not a list of vulns")
        ids = [v.get("id") for v in vulns]
        if not all(isinstance(i, str) and _ID.fullmatch(i) for i in ids):
            raise ValueError("an id that is not shaped like one")
        hits.append(list(dict.fromkeys(ids)))
        complete = complete and not result.get("next_page_token")
    return hits, complete


async def _record(client: httpx.AsyncClient, vid: str, limit: asyncio.Semaphore) -> dict | None:
    """One advisory's record, or None when it does not answer as that record."""
    async with limit:
        try:
            rec = await _json(client, "GET", f"{OSV}/v1/vulns/{quote(vid, safe='')}", "vuln")
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("osv: no record for %s (%s)", vid, type(exc).__name__)
            return None
    return rec if isinstance(rec, dict) and rec.get("id") == vid else None


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _dict(value) -> dict:
    """A record is outside data: each part is read only when it has the type the parser expects, so an odd shape
    makes that record unknown and never breaks the card."""
    return value if isinstance(value, dict) else {}


def _severity(rec: dict | None) -> str:
    word = _dict(_dict(rec).get("database_specific")).get("severity")
    word = word.upper() if isinstance(word, str) else ""
    return word if word in SEVERITY else "UNKNOWN"


def _fixed(rec: dict | None, ecosystem: str, name: str) -> list[str]:
    """The versions the record says fix this package: only its own entries (an advisory can cover several), and only
    version ranges (ECOSYSTEM, SEMVER), never a GIT range's commit hash (#661 max review)."""
    out = []
    for affected in map(_dict, _list(_dict(rec).get("affected"))):
        pkg = _dict(affected.get("package"))
        if pkg.get("ecosystem") != ecosystem or _name(ecosystem, str(pkg.get("name") or "")) != _name(ecosystem, name):
            continue
        for rng in map(_dict, _list(affected.get("ranges"))):
            if rng.get("type") not in ("ECOSYSTEM", "SEMVER"):
                continue
            for event in map(_dict, _list(rng.get("events"))):
                if isinstance(event.get("fixed"), str):
                    out.append(untrusted.clean_name(event["fixed"], 60))
    return [v for v in out if v]


_RELEASE = re.compile(r"^v?([0-9]+(?:\.[0-9]+)*)(.*)$")
_AFTER = re.compile(r"^[._-]?(?:post|rev|r)[0-9]*(?![a-z])", re.I)          # 1.0.post1, never 1.0-rc1


def _vkey(version: str):
    """A version for ordering, or None when it does not read as one: its release numbers (1.2 is 1.2.0), then a
    pre-release (-rc1, a1, .dev3) below the release, the release, and a post-release (.post1) above it."""
    m = _RELEASE.match(version)
    if not m:
        return None
    nums = [int(n) for n in m.group(1).split(".")]
    while len(nums) > 1 and nums[-1] == 0:
        nums.pop()
    rest = m.group(2)
    tag = 1 if not rest or rest.startswith("+") else 2 if _AFTER.match(rest) else 0
    return (tuple(nums), tag, [(0, int(p), "") if p.isdecimal() and p.isascii() else (1, 0, p)
                               for p in re.split(r"([0-9]+)", rest)])


def _versions(found, installed: str = "") -> list[str]:
    """The fixed versions above the installed one, once each, in version order, at most FIXED_MAX; none when none is
    above it, or when either side does not read as a version (#661 max review: "fixed in 1.0.1" next to an installed
    1.2.0 read as already fixed)."""
    floor = _vkey(installed) if installed else None
    if floor is None:
        return []
    above = {v: k for v in set(found) if (k := _vkey(v)) is not None and k > floor}
    return sorted(above, key=above.__getitem__)[:FIXED_MAX]


def _advisories(ids: list[str], records: dict, ecosystem: str, name: str, installed: str = "") -> list[dict]:
    """One package's ids as advisories: ids whose records alias each other are one, under its GitHub id. `loaded` is
    false when no record of it answered: its severity, summary and fixes are then unknown, not none."""
    group = {vid: vid for vid in ids}

    def root(vid):
        while group[vid] != vid:
            vid = group[vid]
        return vid
    for vid in ids:
        for alias in _list(_dict(records.get(vid)).get("aliases")):
            if isinstance(alias, str) and alias in group:
                group[root(alias)] = root(vid)
    members: dict[str, list[str]] = {}
    for vid in ids:
        members.setdefault(root(vid), []).append(vid)
    out = []
    for same in members.values():
        lead = next((v for v in same if v.startswith("GHSA-")), same[0])
        recs = [records.get(v) for v in [lead, *same]]
        summary = next((r["summary"] for r in recs if isinstance(r, dict) and isinstance(r.get("summary"), str)), None)
        out.append({"id": lead, "ids": [lead, *(v for v in same if v != lead)],
                    "severity": max((_severity(r) for r in recs), key=SEVERITY.index),
                    "summary": untrusted.clean_name(summary, SUMMARY_MAX) if summary else None,
                    "loaded": any(isinstance(r, dict) for r in recs),
                    "fixed": _versions((f for v in same for f in _fixed(records.get(v), ecosystem, name)), installed)})
    return sorted(out, key=lambda a: SEVERITY.index(a["severity"]), reverse=True)


def _own_index(packages: list[dict], ecosystem: str, identifier: str) -> int | None:
    """The package being installed. npm: the lock's top-level entry for it (`node_modules/<identifier>`), never a
    nested older copy or an alias that sorts first (#661 max review); a lock without paths falls back to the entry
    whose folder and real name are both the identifier. PyPI's lock is flat: its normalized name."""
    for i, p in enumerate(packages):
        if ecosystem == "npm":
            if p.get("path") == f"node_modules/{identifier}" or (
                    "path" not in p and p.get("name") == identifier and (p.get("registry_name") or identifier) == identifier):
                return i
        elif _name(ecosystem, str(p.get("registry_name") or p.get("name") or "")) == _name(ecosystem, identifier):
            return i
    return None


def _worst(advisories: list[dict]):
    return max((a["severity"] for a in advisories), key=SEVERITY.index) if advisories else None


async def _check(ecosystem: str, identifier: str, packages: list[dict]) -> dict:
    from server.services.capability_install import _LOCK_TEXT
    own = _own_index(packages, ecosystem, identifier)
    # The package itself is asked first, so a lock past QUERIES_MAX never leaves it out; the same name@version at
    # several npm paths is asked once (#661 max review).
    queries, folders, at = [], [], {}
    for i in ([own] if own is not None else []) + [i for i in range(len(packages)) if i != own]:
        p = packages[i]
        query = {"package": {"name": _LOCK_TEXT.sub("", str(p.get("registry_name") or p.get("name") or ""))[:214],
                             "ecosystem": ecosystem},
                 "version": _LOCK_TEXT.sub("", str(p.get("version") or ""))[:60]}
        key = (query["package"]["name"], query["version"])
        if key in at:
            continue
        at[key] = len(queries)
        queries.append(query)
        folders.append(_LOCK_TEXT.sub("", str(p.get("name") or ""))[:214])
    asked = queries[:QUERIES_MAX]
    own_q = 0 if own is not None else None
    async with httpx.AsyncClient(timeout=DEADLINE_S) as client:
        hits, complete = _hits(await _json(client, "POST", f"{OSV}/v1/querybatch", "batch", {"queries": asked}),
                               len(asked))
        wanted = list(dict.fromkeys(vid for ids in hits for vid in ids))
        limit = asyncio.Semaphore(8)
        fetched = await asyncio.gather(*(_record(client, vid, limit) for vid in wanted[:LOOKUPS_MAX]))
    records = dict(zip(wanted, fetched))
    found = {i: _advisories(hits[i], records, ecosystem, asked[i]["package"]["name"], asked[i]["version"])
             for i in range(len(asked)) if hits[i]}
    every = [a for advisories in found.values() for a in advisories]
    mine = found.get(own_q, []) if own_q is not None else []
    theirs = [a for i, advisories in found.items() if i != own_q for a in advisories]
    deps = [{"name": untrusted.clean_name(asked[i]["package"]["name"], 214),
             "alias": untrusted.clean_name(folders[i], 214) if folders[i] != asked[i]["package"]["name"] else None,
             "version": untrusted.clean_name(asked[i]["version"], 60),
             "more": max(0, len(found[i]) - SHOWN_MAX), "advisories": found[i][:SHOWN_MAX]}
            for i in range(len(asked)) if i != own_q and i in found]
    return {"state": "checked", "source": "OSV.dev", "packages": len(queries), "asked": len(asked),
            # incomplete: a lock past the limit, a result with more pages, records past the lookup limit or one
            # that did not answer (#661 max review)
            "complete": complete and len(asked) == len(queries) and len(wanted) <= LOOKUPS_MAX
                        and all(r is not None for r in fetched),
            "count": len(every), "highest": _worst(every),
            "own_highest": _worst(mine), "deps_highest": _worst(theirs),
            "own": mine[:SHOWN_MAX], "own_more": max(0, len(mine) - SHOWN_MAX),
            "deps": deps[:SHOWN_MAX], "deps_more": max(0, len(deps) - SHOWN_MAX)}


async def check(candidate: dict, prepared: dict | None) -> dict:
    """What OSV.dev knows of the packages `prepared`'s lock holds, for the install card (see the module's text)."""
    if candidate.get("kind") != "mcp":
        return {"state": "skipped", "why": "skill"}
    runtime = (prepared or {}).get("runtime") or candidate.get("runtime")
    if runtime == "remote":
        return {"state": "skipped", "why": "remote"}
    if runtime == "mcpb":
        return {"state": "skipped", "why": "bundle"}
    lock, ecosystem = (prepared or {}).get("lock"), ECOSYSTEM.get(runtime)
    if not lock or ecosystem is None:
        return {"state": "skipped", "why": "no_lock"}
    identifier = str((candidate.get("package") or {}).get("identifier") or "")
    if not lock.get("packages"):
        return {"state": "not_checked", "why": "empty_lock"}
    try:
        return await within(_check(ecosystem, identifier, list(lock.get("packages") or [])), DEADLINE_S)
    except (httpx.HTTPError, ValueError, TimeoutError) as exc:
        logger.info("osv: not checked (%s)", type(exc).__name__)
        return dict(NOT_CHECKED)
