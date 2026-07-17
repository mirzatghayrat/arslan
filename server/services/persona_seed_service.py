"""Persona seed library: import agency-agents personas; FTS5 search for the drafter."""
from __future__ import annotations

import logging
import re

import httpx
from sqlalchemy import func, select, text as sa_text

from server.db import session as db_session
from server.db.models import PersonaSeed
from server.services import github_eval  # reuse _GITHUB_API / _token / _headers (fixed host)

logger = logging.getLogger(__name__)

_SECTION = re.compile(r"^#{1,3}\s*(identity|mission|rules?|deliverables?|workflow|success\s*metrics)\b",
                      re.IGNORECASE | re.MULTILINE)

# Word tokens: alphanumeric runs or CJK chars. Mirrors knowledge.py's safe-FTS helper.
_TOKEN = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")

# Top-level dirs in agency-agents that are NOT persona divisions (tooling/docs/examples).
_NON_PERSONA_DIRS = {".github", "scripts", "examples", "docs", "tests"}


def _is_persona_path(path: str) -> bool:
    """True only for real `<division>/<name>.md` persona files.

    Excludes nested READMEs, the PR template, and non-persona top-level dirs so junk
    files don't collapse onto a single slug and pollute the library.
    """
    if not path.endswith(".md") or "/" not in path:
        return False
    if path.rsplit("/", 1)[-1].lower().startswith("readme"):
        return False
    return path.split("/", 1)[0] not in _NON_PERSONA_DIRS


def _fts_query(text: str) -> str:
    """Quoted/OR-joined FTS5 MATCH string (mirrors knowledge.py) so arbitrary input is safe."""
    toks = _TOKEN.findall(text or "")
    return " OR ".join(f'"{t}"' for t in toks)


async def search(query: str, k: int = 3) -> list[dict]:
    """Top-k persona seeds matching the query (by FTS). Returns dicts; [] on empty/no match."""
    q = _fts_query(query)
    if not q:
        return []
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(sa_text(
            "SELECT ps.slug, ps.name, ps.division, ps.raw, ps.deliverables, ps.workflow "
            "FROM persona_seeds_fts f JOIN persona_seeds ps ON ps.id = f.rowid "
            "WHERE f.text MATCH :q ORDER BY rank LIMIT :k"), {"q": q, "k": k})).mappings().all()
        return [dict(r) for r in rows]


async def count() -> int:
    """Number of persona seeds in the library."""
    async with db_session.AsyncSessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(PersonaSeed))).scalar_one()


def _summary(seed: PersonaSeed) -> str:
    """A short one-line gist for browsing/chips (prefer mission, else identity)."""
    text = (seed.mission or seed.identity or "").strip().replace("\n", " ")
    return text[:160]


async def list_seeds(query: str | None = None, *, limit: int = 60, offset: int = 0) -> list[dict]:
    """Browse the seed library. With a query, FTS-rank; otherwise alphabetical by name.
    Returns {slug, name, division, summary} dicts for the panel."""
    async with db_session.AsyncSessionLocal() as db:
        q = _fts_query(query or "")
        if q:
            rows = (await db.execute(sa_text(
                "SELECT ps.slug, ps.name, ps.division, ps.mission, ps.identity "
                "FROM persona_seeds_fts f JOIN persona_seeds ps ON ps.id = f.rowid "
                "WHERE f.text MATCH :q ORDER BY rank LIMIT :limit OFFSET :offset"),
                {"q": q, "limit": limit, "offset": offset})).mappings().all()
            return [{"slug": r["slug"], "name": r["name"], "division": r["division"],
                     "summary": ((r["mission"] or r["identity"] or "").strip().replace("\n", " "))[:160]}
                    for r in rows]
        rows = (await db.execute(
            select(PersonaSeed).order_by(PersonaSeed.name).limit(limit).offset(offset)
        )).scalars().all()
        return [{"slug": s.slug, "name": s.name, "division": s.division, "summary": _summary(s)} for s in rows]


async def get_by_slugs(slugs: list[str]) -> list[dict]:
    """Resolve seed slugs → display dicts, preserving the given order. Unknown slugs are dropped."""
    wanted = [s for s in slugs if s]
    if not wanted:
        return []
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(PersonaSeed).where(PersonaSeed.slug.in_(wanted))
        )).scalars().all()
        by_slug = {s.slug: s for s in rows}
        return [{"slug": s, "name": by_slug[s].name, "division": by_slug[s].division,
                 "summary": _summary(by_slug[s])}
                for s in wanted if s in by_slug]


def _parse_persona(path: str, md: str) -> dict:
    """Parse an agency-agents persona markdown into structured fields."""
    slug = path.rsplit("/", 1)[-1].removesuffix(".md").strip().lower()
    # H1 title → name
    m = re.search(r"^#\s+(.+)$", md, re.MULTILINE)
    name = m.group(1).strip() if m else slug
    division = path.split("/", 1)[0] if "/" in path else None
    # split into sections by H1-3 headers we care about
    fields = {"identity": "", "mission": "", "rules": "", "deliverables": "",
              "workflow": "", "success_metrics": ""}
    parts = _SECTION.split(md)
    # parts alternates: [pre, header1, body1, header2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        key = parts[i].strip().lower().replace(" ", "_").rstrip("s")
        body = parts[i + 1].strip()
        if key.startswith("rule"):
            fields["rules"] = body
        elif key.startswith("deliverable"):
            fields["deliverables"] = body
        elif key.startswith("success"):
            fields["success_metrics"] = body
        elif key in fields:
            fields[key] = body
    return {"slug": slug, "name": name, "division": division, "raw": md, **fields}


async def _list_md_paths(owner: str, repo: str) -> list[str]:
    """List all .md persona paths via the git trees API (fixed host)."""
    token = await github_eval._token()
    url = f"{github_eval._GITHUB_API}/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers=github_eval._headers(token))
        r.raise_for_status()
        tree = r.json().get("tree", [])
    return [t["path"] for t in tree if t.get("type") == "blob" and _is_persona_path(t["path"])]


async def _fetch_md(owner: str, repo: str, path: str) -> str:
    token = await github_eval._token()
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
    async with httpx.AsyncClient(timeout=30) as c:
        # Token intentionally forwarded so private-repo raw fetches work — do not strip.
        r = await c.get(url, headers=github_eval._headers(token))
        r.raise_for_status()
        return r.text


async def import_from_repo(owner: str = "msitarzewski", repo: str = "agency-agents") -> int:
    """Fetch + parse persona markdowns, upsert by slug, (re)build FTS rows. Returns count imported.
    Curation-only: writes persona_seeds + FTS, never creates spawns. Fixed GitHub host (non-SSRF).

    Failure handling is intentionally asymmetric: a listing failure (auth/rate-limit/network)
    propagates so a total import failure surfaces loudly, while a single file's fetch failure is
    logged and skipped best-effort so one bad file doesn't abort the batch."""
    paths = await _list_md_paths(owner, repo)
    n = 0
    for path in paths:
        try:
            md = await _fetch_md(owner, repo, path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("persona import: fetch failed for %s: %s", path, exc)
            continue
        seed = _parse_persona(path, md)
        # rules/success_metrics intentionally excluded: too boilerplate-y, dilute match relevance.
        fts_text = " ".join(filter(None, [seed["name"], seed["division"], seed["identity"],
                                          seed["mission"], seed["deliverables"], seed["workflow"]]))
        async with db_session.AsyncSessionLocal() as db:
            existing = (await db.execute(select(PersonaSeed).where(
                PersonaSeed.slug == seed["slug"]))).scalar_one_or_none()
            if existing is None:
                existing = PersonaSeed(source=f"{owner}/{repo}", **seed)
                db.add(existing)
                await db.flush()
            else:
                for k, v in seed.items():
                    setattr(existing, k, v)
                await db.execute(sa_text("DELETE FROM persona_seeds_fts WHERE rowid = :r"), {"r": existing.id})
            await db.execute(sa_text("INSERT INTO persona_seeds_fts (rowid, text) VALUES (:r,:t)"),
                             {"r": existing.id, "t": fts_text})
            await db.commit()
        n += 1
    return n
