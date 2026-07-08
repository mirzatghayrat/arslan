"""Bounded mini agent-loop for equipped spawns — thin wrapper over tool_loop
that resolves the spawn's currently-wired tools (Layer-3 gate)."""
from __future__ import annotations

from collections.abc import Callable

from server.orchestrator import tool_loop
from server.registry.service import wired_tools_for_spawn

# Re-export so existing imports keep working.
MAX_TOOL_CALLS = tool_loop.MAX_TOOL_CALLS
TOOL_TIMEOUT_S = tool_loop.TOOL_TIMEOUT_S
_PROTOCOL = tool_loop._PROTOCOL


async def run(
    *,
    spawn_id: int,
    system: str,
    user_content: str,
    history: list[dict],
    current_turn: int,
    emit: Callable[[dict], None],
    on_chunk: Callable[[str], None],
    allow_escalation: bool = True,
    conversation_id: str | None = None,
) -> dict:
    """Run the loop for a spawn. Tools = the spawn's wired ∩ safe ∩ equipped set,
    re-resolved per call (grants may expire). Returns tool_loop's result dict.

    conversation_id is observability-only (PB-3 mcp_degrade_hint events); callers
    without one (spawn private chat / sandbox) pass None and logging no-ops."""
    async def _resolve():
        return await wired_tools_for_spawn(spawn_id, current_turn=current_turn)

    # Native tool-calling loop (same fix as Arslan's answer path): no narration-as-answer, no
    # leak, convergence cap. Spawns get the reliable loop too.
    return await tool_loop.run_native(
        system=system, user_content=user_content, history=history,
        emit=emit, on_chunk=on_chunk, resolve_tools=_resolve,
        allow_escalation=allow_escalation, force_tools=True,
        conversation_id=conversation_id,
    )
