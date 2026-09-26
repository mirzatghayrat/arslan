"""Non-persistent text/image turn runtime. No background learning or tool writes.

Temporary mode currently supports conversation and explicitly attached material,
not commands, external actions, or autonomous experts. This is an execution gate,
not a frontend-only privacy label. Provider-side retention is outside this store.
"""
import asyncio
import itertools
import time

from arslan.llm import usage_sink
from server.services import run_registry

_ids = itertools.count(-1, -1)
_sessions: dict[str, tuple[float, list[dict]]] = {}
_live_tokens: dict[str, int] = {}
_MAX_HISTORY_CHARS = 64_000
_IDLE_SECONDS = 1800


def clear(conversation_id: str):
    _sessions.pop(conversation_id, None)
    _live_tokens.pop(conversation_id, None)
    for run_id in run_registry.active_for(conversation_id):
        if run_id < 0:
            run_registry.cancel(run_id)


def history(conversation_id: str) -> list[dict]:
    now = time.monotonic()
    for identity, (updated, _) in list(_sessions.items()):
        if now - updated >= _IDLE_SECONDS:
            clear(identity)
    return list(_sessions.get(conversation_id, (now, []))[1])


def _append(conversation_id: str, role: str, content: str):
    rows = history(conversation_id)
    rows.append({"role": role, "content": content})
    while len(rows) > 1 and sum(len(row["content"]) for row in rows) > _MAX_HISTORY_CHARS:
        rows.pop(0)
    _sessions[conversation_id] = (time.monotonic(), rows)


async def execute(conversation_id, user_message, emit, *, attached_context=None, images=None, **_kwargs):
    from server.orchestrator import arslan, tool_loop
    from server.orchestrator.tool_caller import ToolCaller
    if run_registry.active_for(conversation_id):
        emit({"type": "error", "code": "TASK_ALREADY_RUNNING", "recoverable": True})
        return
    run_id = next(_ids)
    _live_tokens[conversation_id] = run_id
    prior = history(conversation_id)
    _append(conversation_id, "user", user_message)

    async def no_tools():
        return []

    async def run():
        with usage_sink.collecting():
            emit({"type": "stream_start", "source": "arslan", "run_id": run_id, "temporary": True})
            try:
                result = await tool_loop.run_native(
                    system="You are Arslan. Reply in the language of the current user message. "
                           "This is a temporary conversation: use only this conversation and its explicit attachments. "
                           "No tools, external actions, persistent memory, or background workers are available. "
                           "Do not claim to have searched, saved files, or performed actions. "
                           "If the request needs those capabilities, explain that limitation briefly.",
                    user_content=arslan.build_user_blocks(user_message, attached_context, images),
                    history=prior, emit=emit, on_chunk=lambda chunk: emit({"type": "stream_chunk", "content": chunk})
                    if _live_tokens.get(conversation_id) == run_id and not asyncio.current_task().cancelling() else None,
                    resolve_tools=no_tools, allow_escalation=False, log_events=False,
                    caller=ToolCaller(actor="host", spawn_id=None, conversation_id=conversation_id),
                    conversation_id=conversation_id, has_images=bool(images),
                )
                if _live_tokens.get(conversation_id) != run_id or asyncio.current_task().cancelling():
                    raise asyncio.CancelledError
                final = result.get("final") or ""
                _append(conversation_id, "assistant", final)
                emit({"type": "stream_end", "message_id": None, "run_id": run_id,
                      "temporary": True, "usage": arslan._usage_frame(usage_sink.detail())})
            except asyncio.CancelledError:
                emit({"type": "run_cancelled", "run_id": run_id})
                raise
            except Exception:
                # Provider exceptions can contain request bodies; don't persist or
                # repeat them in a temporary transcript or application log.
                emit({"type": "error", "code": "TEMPORARY_TURN_FAILED", "recoverable": True})

    task = asyncio.create_task(run())
    run_registry.register(run_id, conversation_id, task)
    try:
        await task
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise
    finally:
        run_registry.unregister(run_id, conversation_id)
        if _live_tokens.get(conversation_id) == run_id:
            _live_tokens.pop(conversation_id, None)
