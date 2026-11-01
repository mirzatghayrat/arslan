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
  that does not answer still counts, as UNKNOWN.
- **Not asked:** a remote server (nothing is installed here), an MCP bundle (no ecosystem OSV knows) and a skill
  (it names no packages): `{"state": "skipped", "why": …}`.
- **What the card does with a hit is the user's question 5** (block, or only warn), still open. Until it is
  decided this only puts the facts on the card: the buttons stay as they are, and nothing is refused here.

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
    """The versions the record says fix this package (only its own entries: an advisory can cover several)."""
    out = []
    for affected in map(_dict, _list(_dict(rec).get("affected"))):
        pkg = _dict(affected.get("package"))
        if pkg.get("ecosystem") != ecosystem or _name(ecosystem, str(pkg.get("name") or "")) != _name(ecosystem, name):
            continue
        for rng in map(_dict, _list(affected.get("ranges"))):
            for event in map(_dict, _list(rng.get("events"))):
                if isinstance(event.get("fixed"), str):
                    out.append(untrusted.clean_name(event["fixed"], 60))
    return [v for v in out if v]


def _versions(found) -> list[str]:
    """Versions once each, in version order (1.9.0 before 1.10.0), the first FIXED_MAX. Only decimal digits are
    read as numbers: a superscript is text (#661 review), so one odd value never drops the advisory."""
    key = lambda v: [(0, int(p), "") if p.isdecimal() else (1, 0, p) for p in re.split(r"(\d+)", v)]  # noqa: E731
    return sorted(set(found), key=key)[:FIXED_MAX]


def _advisories(ids: list[str], records: dict, ecosystem: str, name: str) -> list[dict]:
    """One package's ids as advisories: ids whose records alias each other are one, under its GitHub id."""
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
                    "fixed": _versions(f for v in same for f in _fixed(records.get(v), ecosystem, name))})
    return sorted(out, key=lambda a: SEVERITY.index(a["severity"]), reverse=True)


async def _check(ecosystem: str, identifier: str, packages: list[dict]) -> dict:
    asked = packages[:QUERIES_MAX]
    queries = [{"package": {"name": str(p.get("registry_name") or p.get("name") or ""), "ecosystem": ecosystem},
                "version": str(p.get("version") or "")} for p in asked]
    folders = [str(p.get("name") or "") for p in asked]
    async with httpx.AsyncClient(timeout=DEADLINE_S) as client:
        hits, complete = _hits(await _json(client, "POST", f"{OSV}/v1/querybatch", "batch", {"queries": queries}),
                               len(queries))
        own = next((i for i, q in enumerate(queries)
                    if _name(ecosystem, q["package"]["name"]) == _name(ecosystem, identifier)), None)
        order = ([own] if own is not None else []) + [i for i in range(len(queries)) if i != own]
        wanted = list(dict.fromkeys(vid for i in order for vid in hits[i]))
        limit = asyncio.Semaphore(8)
        fetched = await asyncio.gather(*(_record(client, vid, limit) for vid in wanted[:LOOKUPS_MAX]))
    records = dict(zip(wanted, fetched))
    found = {i: _advisories(hits[i], records, ecosystem, queries[i]["package"]["name"]) for i in order if hits[i]}
    every = [a for advisories in found.values() for a in advisories]
    deps = [{"name": untrusted.clean_name(queries[i]["package"]["name"], 214),
             "alias": untrusted.clean_name(folders[i], 214) if folders[i] != queries[i]["package"]["name"] else None,
             "version": untrusted.clean_name(queries[i]["version"], 60),
             "more": max(0, len(found[i]) - SHOWN_MAX), "advisories": found[i][:SHOWN_MAX]}
            for i in order if i != own and i in found]
    return {"state": "checked", "source": "OSV.dev", "packages": len(packages),
            "complete": complete and len(asked) == len(packages) and len(wanted) <= LOOKUPS_MAX,
            "count": len(every),
            "highest": max((a["severity"] for a in every), key=SEVERITY.index) if every else None,
            "own": found.get(own, [])[:SHOWN_MAX] if own is not None else [], "deps": deps[:SHOWN_MAX]}


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
