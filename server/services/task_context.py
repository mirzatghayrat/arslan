"""Trusted per-turn binding for personal context and explicit save authority."""
import hashlib
import re
from dataclasses import replace
from functools import wraps
from uuid import uuid4

from arslan.companion.content_policy import normalized_memory
from server.db import session as db_session
from server.db.models import ConversationContext
from server.services import personal_context as pc
from server.services.memory_repository import is_active


def explicit_save_digest(user_message: str) -> str | None:
    """A narrow deterministic command, never a model's interpretation of intent.

    Only an exact content match receives direct-save authority; paraphrases still
    produce proposals. Unrecognized phrasing is safe to confirm through the UI.
    """
    match = re.fullmatch(
        r"(?:please\s+)?remember(?:\s+that)?[\s:：,，]+(.+)"
        r"|(?:请)?(?:记住|记下)[\s:：,，]*(.+)"
        r"|(?:覚えて|記憶して)[\s:：,，]*(.+)"
        r"|(?:recuerda|souviens-toi|merke dir)[\s:：,，]+(.+)",
        user_message.strip(), re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    content = next(value.strip() for value in match.groups() if value is not None)
    return hashlib.sha256(normalized_memory(content).encode()).hexdigest() if content else None


def precise_text_request(message: str) -> bool:
    return len(message) <= 1200 and bool(re.search(
        r"只(?:需)?(?:输出|回答|回复)|仅(?:输出|回答|回复)|(?:output|reply|respond|return)\s+only"
        r"|only\s+(?:output|reply|respond|return)|回答は.+だけ|のみ(?:出力|回答)"
        r"|(?:responde|devuelve)\s+solo|(?:réponds|retourne)\s+uniquement|(?:antworte|gib)\s+nur",
        message, re.IGNORECASE,
    ))


async def load(conversation_id: str, *, user_message="") -> pc.TaskMemoryContext:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(ConversationContext, conversation_id)
        from server.services.llm_factory import memory_models_are_local
        model_is_local = await memory_models_are_local(db)
        if not model_is_local and not (row and row.temporary):
            from sqlalchemy import text
            local_history = await db.scalar(text("""
                SELECT 1 FROM context_receipts WHERE conversation_id=:cid AND owner_id=:owner
                AND (json_extract(receipt,'$.local_only_used')=1
                  OR (json_type(receipt,'$.local_only_used') IS NULL
                      AND json_extract(receipt,'$.cloud_use')='not_sent'
                      AND json_array_length(receipt,'$.used')>0)) LIMIT 1
            """), {"cid": conversation_id, "owner": row.owner_id if row else "local"})
            if local_history:
                from arslan.companion.memory import MemoryError
                raise MemoryError("conversation_local_history")
    identity = str(uuid4())
    digest = explicit_save_digest(user_message)
    return pc.TaskMemoryContext(
        task_id=identity, run_id=f"turn-{identity}", conversation_id=conversation_id,
        owner_id=row.owner_id if row else "local", project_id=row.project_id if row else None,
        model_is_local=model_is_local,
        no_memory=bool(row.no_memory) if row else False,
        no_learning=bool(row.no_learning) if row else False,
        temporary=bool(row.temporary) if row else False,
        cloud_memory_allowed=bool(row.cloud_memory_allowed) if row else False,
        allow_sensitive=bool(row.allow_sensitive) if row else False,
        explicit_save_digest=digest, explicit_save_ref=f"turn:{identity}" if digest else None,
        allow_global_save=bool(digest) and not (row and row.project_id),
    )


async def is_temporary(conversation_id: str) -> bool:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(ConversationContext, conversation_id)
        return bool(row and row.temporary)


def source_message(message_id: int):
    ctx = pc.current()
    if ctx:
        pc._current.set(replace(ctx, source_message_id=message_id,
                               explicit_save_ref=f"message:{message_id}" if ctx.explicit_save_digest else None))


def scoped_turn(function):
    @wraps(function)
    async def wrapped(conversation_id, user_message, *args, **kwargs):
        if pc.current() is not None:
            if pc.current().temporary:
                from server.services.temporary_turn import execute
                return await execute(conversation_id, user_message, *args, **kwargs)
            from server.services.task_service import run_turn
            return await run_turn(function, conversation_id, user_message, *args, **kwargs)
        if not await is_active():
            return await function(conversation_id, user_message, *args, **kwargs)
        ctx = await load(conversation_id, user_message=user_message)
        with pc.bind(ctx):
            if ctx.temporary:
                from server.services.temporary_turn import execute
                return await execute(conversation_id, user_message, *args, **kwargs)
            from server.services.task_service import run_turn
            return await run_turn(function, conversation_id, user_message, *args, **kwargs)
    return wrapped


def scoped_worker(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        with pc.for_worker(str(kwargs["spawn_id"])):
            if pc.current() is not None and kwargs.get("run_id") is not None:
                pc._current.set(replace(pc.current(), run_id=f"run:{kwargs['run_id']}",
                                        source_run_id=kwargs["run_id"]))
            return await function(*args, **kwargs)
    return wrapped


async def execute_entry(conversation_id, instruction, emit, body, *, driver=None,
                        task_id=None, headless=False):
    """Bind non-chat entry points without deriving new consent from saved text."""
    from server.services import task_service
    if task_service.current() is not None or not await is_active():
        return await body(emit)
    ctx = pc.current() or await load(conversation_id, user_message="" if headless else instruction)
    if ctx.temporary:
        from arslan.companion.memory import MemoryError
        raise MemoryError("temporary_tools_unavailable")
    if task_id:
        ctx = replace(ctx, task_id=task_id)
    if headless:
        ctx = replace(ctx, explicit_save_digest=None, explicit_save_ref=None, allow_global_save=False)
    async def function(_conversation, _instruction, sink):
        return await body(sink)
    with pc.bind(ctx):
        if task_id:
            from server.db.models import CompanionTask
            async with db_session.AsyncSessionLocal() as db:
                existing = await db.get(CompanionTask, task_id)
            if existing is not None:
                return await task_service.resume_entry(task_id, existing.version, conversation_id,
                    instruction, emit, body, ctx=ctx, driver=driver)
        return await task_service.run_turn(function, conversation_id, instruction, emit, _driver=driver)


def scoped_dispatch(function):
    @wraps(function)
    async def wrapped(conversation_id, spawn_id, task_brief, emit, *args, **kwargs):
        async def body(sink):
            return await function(conversation_id, spawn_id, task_brief, sink, *args, **kwargs)
        instruction = kwargs.get("user_message") or task_brief
        refinement = kwargs.get("instruction")
        if refinement and refinement != instruction:
            instruction = f"{instruction}\n\nRequested refinement:\n{refinement}"
        if task_brief and task_brief not in instruction:
            instruction = f"Task brief:\n{task_brief}\n\nUser request:\n{instruction}"
        return await execute_entry(conversation_id, instruction, emit, body,
                                   driver={"kind": "expert", "id": spawn_id})
    return wrapped
