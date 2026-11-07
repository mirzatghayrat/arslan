"""One turn of the native loop, as typed values (LOOP1 b): what the caller asks for, what the turn holds while it runs,
and what every tool call of the turn shares. A new input goes on `TurnRequest`, never as another parameter down the loop."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.orchestrator.tool_caller import ToolCaller

TOOL_TIMEOUT_S = 20.0

ResolveTools = Callable[[], Awaitable[list[dict]]]
# (command, argv, *, remote_host=, fingerprints=, sandbox=, why=) -> approved
ConfirmCommand = Callable[..., Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class TurnRequest:
    """What one caller asks of one turn. `run_native` builds it once from its keywords; it doesn't change after that."""
    system: str
    user_content: str
    history: list[dict]
    emit: Callable[[dict], None]
    on_chunk: Callable[[str], None]
    resolve_tools: ResolveTools
    resolve_callable: ResolveTools | None = None
    allow_escalation: bool = True
    max_tool_calls: int | None = None
    tool_timeout_s: float = TOOL_TIMEOUT_S
    force_tools: bool = False
    confirm_command: ConfirmCommand | None = None
    confirm_workspace_write: Any = None
    confirm_schedule: Any = None
    conversation_id: str | None = None
    log_events: bool = True
    caller: ToolCaller | None = None
    has_images: bool = False
    adapter_override: Any = None
    stream_without_tools: bool = False
    progress_lane: Any = None
    turn_notes: list[str] | None = None
    steerable: bool = False


@dataclass(slots=True)
class TurnState:
    """What a turn holds while it runs. `run_native` reads it however the turn ends, a budget stop included."""
    tool_trace: list[dict] = field(default_factory=list)
    recalled_lessons: list[dict] = field(default_factory=list)
    ws_root: Any = None
    started: float = 0.0
    turn_text: Any = None
    steers: list = field(default_factory=list)      # read after a batch, and not yet carried by a request (K9b)


@dataclass(frozen=True, slots=True)
class ToolTurn:
    """What every tool call of one turn goes through its gates with. A read that runs next to others (parallel_reads)
    gets its own copy with its own records: `emit`, `tool_trace`, `convo`."""
    resolve_tools: ResolveTools
    emit: Callable[[dict], None]
    tool_timeout_s: float
    tool_trace: list[dict]
    convo: list[dict]
    confirm_command: ConfirmCommand | None = None
    confirm_workspace_write: Any = None
    confirm_schedule: Any = None
    mcp_fail_counts: dict | None = None
    mcp_hint_logged: set | None = None
    conversation_id: str | None = None
    log_events: bool = True
    caller: ToolCaller | None = None
    turn_adapter: Any = None
    resolve_callable: ResolveTools | None = None
