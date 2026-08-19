"""Discovery orchestration: evaluate_ref (github_eval + mcp_suggest) + curated candidate catalog.
The catalog is read-only curation; the only ingestion path remains P2b add_server."""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import DiscoveryCandidate, SkillPack
from server.services import github_eval, mcp_suggest, repo_overview, skill_suggest


async def evaluate_ref(owner: str, repo: str) -> dict:
    meta = await github_eval.fetch_repo(owner, repo)
    readme = await github_eval.fetch_readme(owner, repo)
    suggestion = await mcp_suggest.classify_and_suggest(meta, readme)
    overview = await repo_overview.explain(meta, readme)
    out = {
        "repo": meta,
        "trust": {
            "tier": github_eval.trust_tier(meta["stars"], meta["pushed_days"]),
            "license_note": github_eval.license_note(meta["license"]),
        },
        "suggestion": suggestion,
        "overview": overview,
    }
    # Third-party packaging contract (spec 2026-08-18 Part B): an author-shipped
    # arslan.plugin.json replaces the LLM guess with declarative config. Broken
    # manifests report but never block — the guess path stays the fallback.
    raw = await github_eval.fetch_file(owner, repo, github_eval.MANIFEST_PATH)
    if raw:
        from server.services import plugin_manifest
        manifest, err = plugin_manifest.validate(raw)
        if manifest is not None:
            out["manifest"] = manifest
        elif err:
            out["manifest_error"] = err
    return out


def _to_dict(row: DiscoveryCandidate) -> dict:
    return {"id": row.id, "full_name": row.full_name, "html_url": row.html_url,
            "snapshot": row.snapshot, "saved_at": row.saved_at.isoformat() if row.saved_at else None}


async def save_candidate(snapshot: dict) -> dict:
    full_name = ((snapshot or {}).get("repo") or {}).get("full_name")
    if not full_name:
        raise ValueError("snapshot.repo.full_name required")
    html_url = (snapshot["repo"] or {}).get("html_url")
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(
            select(DiscoveryCandidate).where(DiscoveryCandidate.full_name == full_name)
        )).scalar_one_or_none()
        if row is None:
            row = DiscoveryCandidate(full_name=full_name)
            db.add(row)
        row.html_url = html_url
        row.snapshot = snapshot
        row.saved_at = datetime.utcnow()
        await db.commit()
        await db.refresh(row)
        return _to_dict(row)


async def list_candidates() -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(DiscoveryCandidate).order_by(DiscoveryCandidate.saved_at.desc())
        )).scalars().all()
        return [_to_dict(r) for r in rows]


async def refresh_candidate(cand_id: int) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(DiscoveryCandidate, cand_id)
        if row is None:
            raise ValueError("candidate not found")
        full_name = row.full_name
    parsed = github_eval.parse_repo_ref(full_name)
    if parsed is None:
        raise ValueError("stored full_name is not parseable")
    snapshot = await evaluate_ref(*parsed)
    return await save_candidate(snapshot)


async def delete_candidate(cand_id: int) -> None:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(DiscoveryCandidate, cand_id)
        if row is not None:
            await db.delete(row)
            await db.commit()


async def generate_skill_draft(owner: str, repo: str) -> dict:
    """Read-only: fetch repo + README → LLM skill draft. Persists nothing."""
    meta = await github_eval.fetch_repo(owner, repo)
    readme = await github_eval.fetch_readme(owner, repo)
    skill = await skill_suggest.generate_skill(meta, readme)
    return {"repo": {"full_name": meta["full_name"], "html_url": meta["html_url"]}, "skill": skill}


def _skill_key(full_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (full_name or "").lower()).strip("-")
    return f"gh-{slug}"[:60]


async def create_skill(full_name: str, name: str, category: str, description: str, body: str) -> dict:
    if not skill_suggest.has_required_sections(body or ""):
        raise ValueError("skill body must contain ## Trigger and ## 决策规则 sections")
    key = _skill_key(full_name)
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(SkillPack, key)
        if row is None:
            row = SkillPack(key=key)
            db.add(row)
        row.name = (name or full_name)[:100]
        row.category = (category or "general")[:40]
        row.description = (description or "")[:300]
        row.tier = "safe"
        row.status = "registered"
        row.body = body
        await db.commit()
        await db.refresh(row)
        return {"key": row.key, "name": row.name, "category": row.category,
                "description": row.description, "tier": row.tier, "status": row.status}
