"""Template listing endpoint wrapping the core TemplateLibrary."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from arslan.templates.library import TemplateLibrary
from server.auth import require_auth
from server.schemas import TemplateOut

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates() -> list[TemplateOut]:
    library = TemplateLibrary()
    library.load_official()
    return [
        TemplateOut(
            name=t.name,
            domain=t.domain,
            description=t.description,
            tags=t.domain_tags + list(t.keywords),
        )
        for t in library.list_all()
    ]
