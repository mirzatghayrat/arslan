"""Human-authored method customization; no model-callable mutation endpoint."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from arslan.companion.contracts import Contract
from server.auth import require_auth
from server.db import session as db_session
from server.services import professional_methods as methods
from server.services.task_repository import TaskError

router = APIRouter(dependencies=[Depends(require_auth)])


class Revision(Contract):
    expected_revision: Annotated[int, Field(ge=1, strict=True)]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    instructions: Annotated[str, Field(min_length=1, max_length=20_000)]


@router.get("/professional-methods")
async def list_methods():
    async with db_session.AsyncSessionLocal() as db:
        values = await methods.list_methods(db)
        await db.commit()
        return values


@router.put("/professional-methods/{key}")
async def revise_method(key: str, body: Revision):
    try:
        async with db_session.AsyncSessionLocal() as db:
            value = await methods.revise(db, key, body.expected_revision, body.name, body.instructions)
            await db.commit()
            return value
    except TaskError as exc:
        raise HTTPException(404 if exc.code.endswith("not_found") else 409, detail={"code": exc.code}) from exc
