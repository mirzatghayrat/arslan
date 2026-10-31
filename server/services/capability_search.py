"""Finding capabilities (0.1.57 §2): the official MCP Registry, GitHub, and reviewed skill
libraries, searched together for what the user wants done.

This is a DISCOVERY layer (tests/server/test_capability_supply_chain.py): it returns
candidates for a person (or the model, as outside content) to read. Nothing here installs,
and no installer imports this module — an install always names one source on a card the
user answers.

Every candidate says where its license was read. In search results that is GitHub's own
detection of the repository's LICENSE file (the source, not a package registry); the
install path (P2) reads the file itself at the pinned commit before anything is fetched.
Package metadata (PyPI, npm, the MCP Registry) is never the basis — the registry has no
license field at all (checked 2026-10-09).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass, field

import httpx

from server.services import github_eval
from server.services.skill_import import ALLOWED_LICENSES
from arslan.aio import within

logger = logging.getLogger(__name__)

REGISTRY = "https://registry.modelcontextprotocol.io"
GITHUB = "https://api.github.com"
TIMEOUT_S = 10.0
#: The official registry answered in 13–60 s per query on 2026-10-09 (≈19 s with
#: version=latest); a slower budget for it, and a longer cache so a word is asked rarely.
REGISTRY_TIMEOUT_S = 30.0
REGISTRY_CACHE_S = 6 * 3600
LIBRARY_TIMEOUT_S = 30.0
CACHE_S = 3600
LIBRARY_CACHE_S = 24 * 3600
MAX_RESULTS = 24
MODEL_RESULTS = 8

#: Reviewed skill libraries (§2): read as an index of SKILL.md files, one license per skill.
SKILL_LIBRARIES = ("anthropics/skills",)

#: How a package runs here (§5.1). Anything else is shown with the reason it cannot.
RUNTIMES = {"pypi": "uv", "npm": "node", "mcpb": "mcpb"}
NOT_HERE = {"nuget": "needs_dotnet", "oci": "needs_docker", "docker": "needs_docker"}

STOPWORDS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "from", "my", "me",
             "read", "write", "use", "using", "can", "how", "do", "does", "file", "files", "tool", "tools",
             "mcp", "server", "skill", "skills", "please", "help"}


@dataclass
class Candidate:
    id: str
    kind: str                     # mcp | skill | project
    name: str
    summary: str
    source: str                   # registry | github | library
    source_url: str | None
    repo: str | None              # owner/repo when known
    version: str | None = None
    runtime: str | None = None    # uv | node | mcpb | remote | skill | None
    package: dict | None = None
    remote: dict | None = None
    not_here: str | None = None   # why it cannot run here: needs_dotnet | needs_docker |
                                  # no_runnable_package | nothing_published | not_in_registry |
                                  # add_by_hand (CAP4a-3c: the user's list does not cover it)
    needs: dict = field(default_factory=lambda: {"keys": [], "network": None})
    license: dict = field(default_factory=lambda: {"spdx": None, "read_from": None, "verdict": "unknown"})
    stars: int | None = None
    pushed_days: int | None = None
    checked_at: float | None = None
    path: str | None = None       # a skill's SKILL.md inside its library
    by_hand: str | None = None    # CAP4a-3c: why it is not one-click (not_here "add_by_hand"), as
                                  # capability_allowlist names it

    def view(self) -> dict:
        return asdict(self)


# ── keywords ─────────────────────────────────────────────────────────────────

def keywords(text: str, extra: list[str] | None = None) -> list[str]:
    """Search words: the given ones first, then Latin words from the text (registry
    names and GitHub topics are English). At most four."""
    out: list[str] = []
    for word in [*(extra or []), *re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{1,30}", text or "")]:
        w = word.strip().lower().strip(".-")
        if w and w not in STOPWORDS and w not in out:
            out.append(w)
    return out[:4]


# ── licenses ─────────────────────────────────────────────────────────────────

def license_verdict(spdx: str | None, *, proprietary: bool = False) -> str:
    """usable | reference_only (a license that forbids reuse) | unknown (none found)."""
    if proprietary:
        return "reference_only"
    if not spdx or spdx == "NOASSERTION":
        return "unknown"
    return "usable" if spdx in ALLOWED_LICENSES else "reference_only"


# ── a tiny cache ─────────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float):
    hit = _cache.get(key)
    return hit[1] if hit and time.time() - hit[0] < ttl else None


def _store(key: str, value):
    _cache[key] = (time.time(), value)
    return value


def clear_cache() -> None:
    _cache.clear()


# ── the official MCP Registry ────────────────────────────────────────────────

def _version_key(v: str | None) -> tuple:
    parts = re.findall(r"\d+|[a-z]+", (v or "").lower())
    return tuple((0, int(p)) if p.isdigit() else (-1, p) for p in parts)


def _repo_of(url: str | None) -> str | None:
    if not url:
        return None
    parsed = github_eval.parse_repo_ref(url.replace("https://github.com/", "").replace("http://github.com/", ""))
    return f"{parsed[0]}/{parsed[1]}" if parsed and "github.com" in url else None


def publisher_of(c: dict) -> dict | None:
    """Who published a candidate, as a fact (CAP4a-1): a Registry name's reverse-DNS namespace, which the Registry
    verified, is a domain the publisher owns (`com.example/notes` -> example.com), and `io.github.<account>/…` a
    GitHub account; a candidate from GitHub is its repository's account. Neither proves "official". An account
    is one GitHub would accept (letters, digits and single hyphens, at most 39), else there is no fact to say."""
    if c.get("source") == "registry":
        namespace = str(c.get("id") or "").removeprefix("registry:").rpartition("@")[0].partition("/")[0]
        if namespace.startswith("io.github."):
            return _github_account(namespace[len("io.github."):])
        labels = namespace.split(".")
        if len(labels) >= 2 and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels):
            return {"kind": "domain", "value": ".".join(reversed(labels))}
        return None
    repo = str(c.get("repo") or "")
    return _github_account(repo.split("/")[0]) if "/" in repo else None


def _github_account(login: str) -> dict | None:
    if re.fullmatch(r"[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}", login):
        return {"kind": "github", "value": login}
    return None


def _deleted(entry: dict) -> bool:
    """The Registry marks a withdrawn entry `deleted` (its official `_meta`, or `status` in older answers)."""
    srv = entry.get("server", entry)
    meta = entry.get("_meta")
    official = meta.get("io.modelcontextprotocol.registry/official") if isinstance(meta, dict) else None
    status = official.get("status") if isinstance(official, dict) else None
    return (status or (srv.get("status") if isinstance(srv, dict) else None)) == "deleted"


def from_registry(entry: dict) -> Candidate:
    srv = entry.get("server", entry)
    name = srv.get("name") or "?"
    repo_url = (srv.get("repository") or {}).get("url")
    cand = Candidate(id=f"registry:{name}@{srv.get('version')}", kind="mcp", name=name.rsplit("/", 1)[-1],
                     summary=(srv.get("description") or "")[:300], source="registry",
                     source_url=repo_url or None, repo=_repo_of(repo_url), version=srv.get("version"))
    if _deleted(entry):                                        # CAP4a-1: never offered
        cand.not_here = "deleted_in_registry"
        return cand
    packages = srv.get("packages") or []
    remotes = srv.get("remotes") or []
    usable = next((p for p in packages if p.get("registryType") in RUNTIMES), None)
    if usable:
        cand.runtime = RUNTIMES[usable["registryType"]]
        cand.package = {"registry_type": usable["registryType"], "identifier": usable.get("identifier"),
                        "version": usable.get("version") or srv.get("version"),
                        "file_sha256": usable.get("fileSha256"), "runtime_hint": usable.get("runtimeHint"),
                        "transport": (usable.get("transport") or {}).get("type"),
                        # How the server is started (e.g. ["stdio", "--allow-dir <folder>"]).
                        "arguments": [{k: a.get(k) for k in ("type", "name", "value", "format", "isRequired")}
                                      for a in usable.get("packageArguments") or [] if isinstance(a, dict)][:12]}
        env = usable.get("environmentVariables") or []
        cand.needs = {"keys": [{"name": e.get("name"), "secret": bool(e.get("isSecret")),
                                "required": bool(e.get("isRequired")), "description": (e.get("description") or "")[:200]}
                               for e in env if e.get("name")], "network": None}
    elif remotes:
        r = remotes[0]
        cand.runtime = "remote"
        cand.remote = {"type": r.get("type"), "url": r.get("url")}
        cand.needs = {"keys": [{"name": h.get("name"), "secret": bool(h.get("isSecret")),
                                "required": bool(h.get("isRequired")), "description": (h.get("description") or "")[:200]}
                               for h in r.get("headers") or [] if h.get("name")], "network": True}
    elif packages:
        kinds = {p.get("registryType") for p in packages}
        cand.not_here = next((NOT_HERE[k] for k in kinds if k in NOT_HERE), "no_runnable_package")
    else:
        cand.not_here = "nothing_published"
    return cand


async def search_registry(client: httpx.AsyncClient, word: str) -> list[Candidate]:
    hit = _cached(f"reg:{word}", REGISTRY_CACHE_S)
    if hit is not None:
        return hit
    r = await client.get(f"{REGISTRY}/v0/servers", params={"search": word, "version": "latest", "limit": 50},
                         timeout=REGISTRY_TIMEOUT_S)
    r.raise_for_status()
    newest: dict[str, dict] = {}
    for entry in r.json().get("servers") or []:
        srv = entry.get("server", entry)
        name = srv.get("name")
        if _deleted(entry):                                    # CAP4a-1: a withdrawn entry is not a result
            continue
        if name and (name not in newest or _version_key(srv.get("version")) >
                     _version_key(newest[name].get("server", newest[name]).get("version"))):
            newest[name] = entry
    return _store(f"reg:{word}", [from_registry(e) for e in newest.values()])


LOOKUPS = 6                      # GitHub MCP repositories checked against the registry by name


async def lookup_registry(client: httpx.AsyncClient, repo: str) -> Candidate | None:
    """The registry entry a GitHub repository published under the usual name
    (io.github.<owner>/<repo>): one fast call (≈0.9 s, against ≈19 s or a timeout for a
    registry search on 2026-10-09). None when it published nothing there."""
    key = f"regname:{repo.lower()}"
    hit = _cached(key, REGISTRY_CACHE_S)
    if hit is not None:
        return hit or None
    owner, name = repo.split("/", 1)
    r = await client.get(f"{REGISTRY}/v0/servers/io.github.{owner}%2F{name}/versions/latest", timeout=TIMEOUT_S)
    if r.status_code == 404:
        _store(key, False)
        return None
    r.raise_for_status()
    return _store(key, from_registry(r.json()))


# ── GitHub ───────────────────────────────────────────────────────────────────

def _kind_from_repo(item: dict) -> str:
    topics = {t.lower() for t in item.get("topics") or []}
    name = (item.get("full_name") or "").lower()
    if topics & {"mcp", "mcp-server", "model-context-protocol", "mcp-servers"} or "mcp" in name:
        return "mcp"
    if topics & {"claude-skills", "agent-skills", "skills", "claude-skill"} or "skill" in name:
        return "skill"
    return "project"


def from_github(item: dict) -> Candidate:
    kind = _kind_from_repo(item)
    spdx = item.get("license")
    cand = Candidate(id=f"github:{item.get('full_name')}", kind=kind, name=(item.get("full_name") or "").split("/")[-1],
                     summary=(item.get("description") or "")[:300], source="github", source_url=item.get("html_url"),
                     repo=item.get("full_name"), stars=item.get("stars"), pushed_days=item.get("pushed_days"),
                     license={"spdx": spdx, "read_from": "github:LICENSE", "verdict": license_verdict(spdx)},
                     checked_at=time.time())
    if kind == "mcp":
        # §2: an MCP server is installed from a published package (the registry), never built
        # from a repository's source; a repository-only server is shown, not offered.
        cand.not_here = "not_in_registry"
    elif kind == "skill":
        cand.runtime = "skill"
    return cand


async def search_github(word: str) -> list[Candidate]:
    hit = _cached(f"gh:{word}", CACHE_S)
    if hit is not None:
        return hit
    items = await github_eval.search_repos(word)     # a rate limit raises: the search notes it
    return _store(f"gh:{word}", [from_github(i) for i in items])


async def enrich_batch(cands: list[Candidate]) -> None:
    """License, stars and last push for many registry entries at once: one GitHub search per
    ~240 characters of `repo:` qualifiers (search allows several), instead of a call per
    repository (the core API allows 60 an hour without a token). Cached per repository."""
    todo = [c for c in cands if c.repo and _cached(f"repo:{c.repo}", CACHE_S) is None]
    chunks, current = [], []
    for c in todo:
        if current and len(" ".join(f"repo:{r.repo}" for r in [*current, c])) > 240:
            chunks.append(current)
            current = []
        current.append(c)
    if current:
        chunks.append(current)
    for chunk in chunks[:3]:
        items = await github_eval.search_repos(" ".join(f"repo:{c.repo}" for c in chunk))
        for item in items:
            if item.get("full_name"):
                _store(f"repo:{item['full_name']}", item)
    for c in cands:
        hit = _cached(f"repo:{c.repo}", CACHE_S) if c.repo else None
        if hit:
            spdx = hit.get("license")
            c.license = {"spdx": spdx, "read_from": "github:LICENSE", "verdict": license_verdict(spdx)}
            c.stars, c.pushed_days, c.checked_at = hit.get("stars"), hit.get("pushed_days"), time.time()


# ── reviewed skill libraries ─────────────────────────────────────────────────

CODELOAD = "https://codeload.github.com"
LIBRARY_MAX_BYTES = 30 * 1024 * 1024


def index_archive(library: str, data: bytes) -> list[Candidate]:
    """Every SKILL.md in a library's archive, with that skill's own license file (§2). The
    archive's pax header carries the commit it was made from (GitHub writes it there), so
    the index — and an import from it — names one exact commit."""
    import io
    import tarfile

    from server.services import skill_import
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        sha = (archive.pax_headers or {}).get("comment") or ""
        files: dict[str, bytes] = {}
        for member in archive.getmembers():
            if not member.isfile() or member.size > 1_000_000:
                continue
            rel = member.name.split("/", 1)[1] if "/" in member.name else member.name
            if rel.endswith("SKILL.md") or rel.rsplit("/", 1)[-1] in skill_import._LICENSE_NAMES:
                fh = archive.extractfile(member)
                if fh is not None:
                    files[rel] = fh.read()
    out: list[Candidate] = []
    for path in sorted(p for p in files if p.endswith("SKILL.md"))[:60]:
        parsed = skill_import.parse_skill_md(files[path].decode("utf-8", "replace"))
        if not parsed:
            continue
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        lic_path = next((f"{folder}/{n}" for n in skill_import._LICENSE_NAMES if folder and f"{folder}/{n}" in files), None)
        spdx = proprietary = None
        if lic_path:
            spdx = skill_import.detect_license(files[lic_path].decode("utf-8", "replace"))
            proprietary = spdx is None                        # a license file that is not permissive
        out.append(Candidate(
            id=f"library:{library}:{path}", kind="skill", name=parsed["name"], summary=parsed["description"],
            source="library", source_url=f"https://github.com/{library}/tree/{sha or 'HEAD'}/{folder}", repo=library,
            version=sha or None, runtime="skill", path=path,     # all 40 digits: the card pins it (#539 review 6)
            license={"spdx": spdx, "read_from": lic_path, "verdict": license_verdict(spdx, proprietary=bool(proprietary))},
            checked_at=time.time()))
    return out


async def library_index(client: httpx.AsyncClient, library: str) -> list[Candidate]:
    """A reviewed library as one archive from codeload (not the rate-limited API: without a
    token GitHub allows 60 API calls an hour, and the per-file way spent ~40 of them)."""
    hit = _cached(f"lib:{library}", LIBRARY_CACHE_S)
    if hit is not None:
        return hit
    r = await client.get(f"{CODELOAD}/{library}/tar.gz/HEAD", follow_redirects=True, timeout=LIBRARY_TIMEOUT_S)
    r.raise_for_status()
    if len(r.content) > LIBRARY_MAX_BYTES:
        raise ValueError("library archive too large")
    return _store(f"lib:{library}", index_archive(library, r.content))


def _matches(cand: Candidate, words: list[str]) -> int:
    hay = f"{cand.name} {cand.summary} {cand.repo or ''}".lower()
    return sum(1 for w in words if w in hay)


# ── together ─────────────────────────────────────────────────────────────────

def rank(cands: list[Candidate], words: list[str]) -> list[Candidate]:
    """One score (§2): fit to the words, a license we can use, can run here, and how widely
    used (log of stars), minus a year without commits. Fit alone buried the server that does
    the job under small repositories that merely mention a word (measured 2026-10-09 with
    "excel formulas"). The model does its own choosing from the top MODEL_RESULTS."""
    import math

    def score(c: Candidate):
        usable = c.license["verdict"] == "usable"
        installable = usable and c.not_here is None and c.runtime in ("uv", "node", "mcpb", "remote", "skill")
        # CAP4a-3c: an entry added by hand still runs here, so it outranks its repository's GitHub copy.
        runs_here = c.not_here in (None, "add_by_hand")
        value = (2 * _matches(c, words) / max(1, len(words)) + 2 * usable + 2 * runs_here
                 + 1.5 * installable                      # something Arslan can actually add, first
                 + math.log10((c.stars or 0) + 1) / 2 - (1 if (c.pushed_days or 0) > 365 else 0))
        return (-value, c.id)
    seen, out = set(), []
    for c in sorted(cands, key=score):
        key = (c.repo or c.id).lower() if c.kind != "skill" or c.source != "library" else c.id
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


async def search(need: str, *, words: list[str] | None = None, kinds: set[str] | None = None) -> dict:
    """{words, candidates, notes}. Each source fails on its own; notes say which did."""
    words = keywords(need, words)
    if not words:
        return {"words": [], "candidates": [], "notes": ["no_keywords"]}
    notes: list[str] = []
    found: list[Candidate] = []
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        budgets = {"registry": REGISTRY_TIMEOUT_S, "library": LIBRARY_TIMEOUT_S, "github": TIMEOUT_S,
                   "registry_lookup": TIMEOUT_S}

        async def guarded(name, coro):
            try:
                return await within(coro, budgets[name] + 2)
            except Exception as exc:  # noqa: BLE001 — one source never stops the others
                logger.info("capability search %s failed: %s", name, type(exc).__name__)
                if name != "registry_lookup" and f"{name}_unavailable" not in notes:
                    notes.append(f"{name}_unavailable")
                return []
        jobs = []
        if not kinds or "mcp" in kinds:
            jobs += [guarded("registry", search_registry(client, w)) for w in words[:2]]
        if not kinds or kinds & {"mcp", "skill", "project"}:
            jobs.append(guarded("github", search_github(" ".join(words[:3]))))
        if not kinds or "mcp" in kinds:
            jobs.append(guarded("github", search_github(" ".join(words[:2]) + " mcp")))
        if not kinds or "skill" in kinds:
            jobs += [guarded("library", library_index(client, lib)) for lib in SKILL_LIBRARIES]
        for batch in await asyncio.gather(*jobs):
            found.extend(batch)
        # The fast way to the registry: GitHub's MCP repositories, looked up by name.
        known = {c.repo.lower() for c in found if c.source == "registry" and c.repo}
        ask = sorted({c.repo for c in found if c.source == "github" and c.kind == "mcp" and c.repo
                      and c.repo.lower() not in known and (not kinds or "mcp" in kinds)}, key=lambda r: -max(
                          (c.stars or 0) for c in found if c.repo == r))[:LOOKUPS]
        for entry in await asyncio.gather(*(guarded("registry_lookup", lookup_registry(client, r)) for r in ask)):
            if isinstance(entry, Candidate):
                found.append(entry)
    found = [c for c in found if c.source != "library" or _matches(c, words)]
    if kinds:
        found = [c for c in found if c.kind in kinds]
    found = merge(found)
    unread = [c for c in found if c.source == "registry" and c.repo and c.license["verdict"] == "unknown"]
    try:
        await within(enrich_batch(unread), TIMEOUT_S + 2)
    except Exception as exc:  # noqa: BLE001 — unread licenses stay "unknown" (not installable)
        logger.info("capability search enrich: %s", type(exc).__name__)
    await mark_by_hand(found)
    return {"words": words, "candidates": [c.view() for c in rank(found, words)[:MAX_RESULTS]], "notes": notes}


async def mark_by_hand(cands: list[Candidate]) -> None:
    """CAP4a-3c: a Registry entry the user's list does not cover is shown, not offered: `not_here` "add_by_hand",
    and `by_hand` says why (capability_allowlist)."""
    from server.services import capability_allowlist
    allow = await capability_allowlist.current()
    for c in cands:
        if c.not_here is None:
            reason = capability_allowlist.verdict(c.view(), allow)
            if reason:
                c.not_here, c.by_hand = "add_by_hand", reason


def merge(cands: list[Candidate]) -> list[Candidate]:
    """A registry entry (installable as a package) takes the GitHub result for the same
    repository — its license, stars and last push — so it needs no lookup of its own; the
    GitHub copy then loses the ranking's one-per-repository pick (it cannot run here)."""
    github = {c.repo.lower(): c for c in cands if c.source == "github" and c.repo}
    for c in cands:
        g = github.get((c.repo or "").lower()) if c.source == "registry" else None
        if g is not None:
            c.license, c.stars, c.pushed_days, c.checked_at = g.license, g.stars, g.pushed_days, g.checked_at
    return cands


# ── what a conversation was shown ────────────────────────────────────────────

_SEEN: dict[str, dict[str, dict]] = {}
_SEEN_CONVERSATIONS = 50


def remember(conversation_id: str | None, result: dict) -> None:
    """Candidates this conversation's model was shown. A proposal (P3) may only name one of
    these: the card is built from what the search returned, never from the model's words."""
    if not conversation_id:
        return
    seen = _SEEN.setdefault(conversation_id, {})
    for c in result["candidates"]:
        seen[c["id"]] = c
    while len(_SEEN) > _SEEN_CONVERSATIONS:
        _SEEN.pop(next(iter(_SEEN)))


def seen(conversation_id: str | None, candidate_id: str) -> dict | None:
    return (_SEEN.get(conversation_id or "") or {}).get(candidate_id)


def for_model(result: dict) -> dict:
    """What `find_capability` returns: the top few, compact, as outside content."""
    out = []
    for c in result["candidates"][:MODEL_RESULTS]:
        out.append({k: c.get(k) for k in ("id", "kind", "name", "summary", "source_url", "version", "runtime",
                                          "not_here", "by_hand", "stars", "pushed_days")} |
                   {"license": c["license"]["spdx"], "license_verdict": c["license"]["verdict"],
                    "needs_keys": [k["name"] for k in c["needs"]["keys"]]})
    return {"words": result["words"], "candidates": out, "notes": result["notes"]}
