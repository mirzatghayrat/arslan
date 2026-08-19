"""Read-only GitHub repo evaluation (fixed host api.github.com — NOT an SSRF surface).
Trust tiers reuse the github-eval seed thresholds."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from server.db import session as db_session
from server.services import settings_service

_GITHUB_API = "https://api.github.com"
_README_LIMIT = 12000
_TIMEOUT = 15.0

_REF_RE = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def parse_repo_ref(text: str) -> tuple[str, str] | None:
    s = (text or "").strip()
    if not s or " " in s.split("/")[0]:
        # quick reject of free text like "not a repo"
        if " " in s:
            return None
    m = _REF_RE.match(s)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    repo = repo.removesuffix(".git")
    if not owner or not repo:
        return None
    return owner, repo


def trust_tier(stars: int, pushed_days: int | None) -> str:
    if stars >= 1000 and pushed_days is not None and pushed_days <= 180:
        return "high"
    if stars >= 100:
        return "medium"
    return "low"


def license_note(spdx: str | None) -> str:
    if not spdx or spdx in ("NOASSERTION",):
        return "无明确 license — 默认不可商用"
    s = spdx.upper()
    if s in ("MIT", "APACHE-2.0", "BSD-3-CLAUSE", "BSD-2-CLAUSE", "ISC"):
        return f"{spdx}: commercial-safe"
    if s.startswith("GPL") or s.startswith("AGPL") or s.startswith("LGPL"):
        return f"{spdx}: copyleft — 传染性警告"
    return f"{spdx}: 人工核对许可"


async def _token() -> str:
    async with db_session.AsyncSessionLocal() as db:
        try:
            return await settings_service.get_decrypted(db, "github_token")
        except Exception:  # noqa: BLE001
            return ""


def _headers(token: str) -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "arslan-toolhub"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _pushed_days(pushed: str | None) -> int | None:
    if not pushed:
        return None
    try:
        dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


_SEARCH_LIMIT = 15


async def fetch_repo(owner: str, repo: str) -> dict:
    token = await _token()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(f"{_GITHUB_API}/repos/{owner}/{repo}", headers=_headers(token))
    if r.status_code == 404:
        raise ValueError("repo not found on GitHub")
    if r.status_code == 403 and "rate limit" in (r.text or "").lower():
        raise ValueError("GitHub rate-limited — set GITHUB_TOKEN in Settings to raise the limit")
    r.raise_for_status()
    d = r.json()
    pushed_days = _pushed_days(d.get("pushed_at"))
    return {
        "full_name": d.get("full_name") or f"{owner}/{repo}",
        "html_url": d.get("html_url") or f"https://github.com/{owner}/{repo}",
        "stars": d.get("stargazers_count", 0),
        "forks": d.get("forks_count", 0),
        "license": (d.get("license") or {}).get("spdx_id"),
        "pushed_days": pushed_days,
        "description": d.get("description") or "",
        "topics": d.get("topics") or [],
    }


async def search_repos(query: str) -> list[dict]:
    q = (query or "").strip()
    if not q:
        raise ValueError("query required")
    token = await _token()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{_GITHUB_API}/search/repositories",
            headers=_headers(token),
            params={"q": q, "sort": "stars", "order": "desc", "per_page": _SEARCH_LIMIT},
        )
    if r.status_code == 403 and "rate limit" in (r.text or "").lower():
        raise ValueError("GitHub rate-limited — set GITHUB_TOKEN in Settings to raise the limit")
    r.raise_for_status()
    items = r.json().get("items") or []
    out: list[dict] = []
    for d in items:
        stars = d.get("stargazers_count", 0)
        pdays = _pushed_days(d.get("pushed_at"))
        spdx = (d.get("license") or {}).get("spdx_id")
        out.append({
            "full_name": d.get("full_name"),
            "html_url": d.get("html_url"),
            "stars": stars,
            "forks": d.get("forks_count", 0),
            "license": spdx,
            "pushed_days": pdays,
            "description": d.get("description") or "",
            "trust": {"tier": trust_tier(stars, pdays), "license_note": license_note(spdx)},
        })
    return out


MANIFEST_PATH = "arslan.plugin.json"
_FILE_LIMIT = 64_000


async def fetch_file(owner: str, repo: str, path: str) -> str:
    """Raw repo file body, "" when absent/unreadable (best-effort like the README).

    Same fixed-host surface: owner/repo/path are PATH SEGMENTS on
    api.github.com — the path guard exists so a manifest-supplied string can
    never smuggle traversal or query tricks into the request (defense here,
    contract in plugin_manifest.safe_repo_path)."""
    from server.services.plugin_manifest import safe_repo_path

    if not safe_repo_path(path):
        raise ValueError(f"unsafe repo path: {path!r}")
    token = await _token()
    headers = {**_headers(token), "Accept": "application/vnd.github.raw"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
                                 headers=headers)
        if r.status_code != 200:
            return ""
        return (r.text or "")[:_FILE_LIMIT]
    except Exception:  # noqa: BLE001  (best-effort, like the README)
        return ""


async def fetch_readme(owner: str, repo: str) -> str:
    token = await _token()
    headers = {**_headers(token), "Accept": "application/vnd.github.raw"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_GITHUB_API}/repos/{owner}/{repo}/readme", headers=headers)
        if r.status_code != 200:
            return ""
        return (r.text or "")[:_README_LIMIT]
    except Exception:  # noqa: BLE001  (README is best-effort)
        return ""
