"""Host-answer lifecycle: persisted Run, shared cancellation, trace and reconnect.

The callback contains conversational behavior; this module owns execution state.
Host runs are not spawn evolution samples and never schedule an automatic judge.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from arslan.llm import usage_sink
from server.orchestrator import run_trace
from server.services import execution_context, run_recorder, run_registry


async def execute(conversation_id: str, user_message: str, emit: Callable[[dict], None],
                  body: Callable[[Callable[[dict], None]], Awaitable[str | None]],
                  *, has_images: bool = False) -> str | None:
    recorder = await run_recorder.RunRecorder.start(
        conversation_id=conversation_id, spawn_id=None, spawn_name="Arslan",
        user_message=user_message, kind="host", has_images=has_images,
    )
    tee = recorder.tee(emit)
    chunks: list[str] = []
    summary_id = None
    error = None

    def capture(event: dict) -> None:
        nonlocal summary_id, error
        event = {**event, "run_id": recorder.run_id}
        if event.get("type") == "stream_start":
            return  # The lifecycle emits the preamble before context retrieval begins.
        if event.get("type") == "stream_chunk":
            chunks.append(event.get("content") or "")
        if event.get("type") == "stream_end":
            summary_id = event.get("message_id")
        if event.get("type") == "error":
            error = event.get("message") or "host execution failed"
        tee(event)

    async def finalize(output: str, *, cancelled: bool = False) -> None:
        usage = usage_sink.detail()
        prompt = run_trace.prompt()
        await recorder.finalize(
            summary_message_id=summary_id, full_output=output,
            model=usage["model"], provider=usage["provider"],
            tokens_in=usage["tokens_in"], tokens_out=usage["tokens_out"],
            tokens_estimated=usage["tokens_in"] is None,
            error_kind="HostError" if error else None, error_text=error,
            system_prompt=prompt["system_prompt"], injected_kb=prompt["injected_kb"],
            injected_kb_sources=prompt.get("injected_kb_sources"),
            status_override="cancelled" if cancelled else None,
        )

    async def run() -> str | None:
        nonlocal error
        with usage_sink.collecting(), run_trace.collecting(), execution_context.bind_run(recorder.run_id):
            tee({"type": "stream_start", "source": "arslan", "run_id": recorder.run_id})
            try:
                output = await body(capture)
                await finalize(output or "".join(chunks))
                return output
            except asyncio.CancelledError:
                await finalize("".join(chunks), cancelled=True)
                tee({"type": "run_cancelled", "run_id": recorder.run_id})
                raise
            except Exception as exc:
                error = str(exc)
                await finalize("".join(chunks))
                raise

    task = asyncio.create_task(run())
    run_registry.register(recorder.run_id, conversation_id, task, recorder=recorder)
    try:
        return await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            task.cancel()
            raise
        if not task.cancelled():
            task.cancel()
            raise
        return None  # User cancelled this Run; keep the WebSocket receive loop alive.
    finally:
        run_registry.unregister(recorder.run_id, conversation_id)
