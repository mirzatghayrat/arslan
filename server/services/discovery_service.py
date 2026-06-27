"""Discovery orchestration: evaluate_ref (github_eval + mcp_suggest) + curated candidate catalog.
The catalog is read-only curation; the only ingestion path remains P2b add_server."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import DiscoveryCandidate
from server.services import github_eval, mcp_suggest


async def evaluate_ref(owner: str, repo: str) -> dict:
    meta = await github_eval.fetch_repo(owner, repo)
    readme = await github_eval.fetch_readme(owner, repo)
    suggestion = await mcp_suggest.classify_and_suggest(meta, readme)
    return {
        "repo": meta,
        "trust": {
            "tier": github_eval.trust_tier(meta["stars"], meta["pushed_days"]),
            "license_note": github_eval.license_note(meta["license"]),
        },
        "suggestion": suggestion,
    }


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
