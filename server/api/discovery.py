"""Read-only discovery layer: evaluate a GitHub repo (trust + MCP classification). Persists nothing.
'Add as MCP server' happens client-side via the existing P2b POST /mcp/servers."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.services import github_eval, mcp_suggest

router = APIRouter(prefix="/discovery", tags=["discovery"])


class EvaluateBody(BaseModel):
    ref: str


@router.post("/evaluate")
async def evaluate(body: EvaluateBody):
    parsed = github_eval.parse_repo_ref(body.ref)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid repo ref — use owner/repo or a github.com URL")
    owner, repo = parsed
    try:
        meta = await github_eval.fetch_repo(owner, repo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
