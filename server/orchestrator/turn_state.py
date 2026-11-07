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
    """What a turn holds while it runs. `run_native` reads it however the turn ends, a budget stop included.

    LOOP1 c3: each phase of the loop writes what it worked out here as it happens, and the next phase reads it here.
    Nothing is worked out again from the trajectory. Values stored at open stay stored: `request_ceiling`,
    `own_folder`, `ws_root`, `offline_note` and `can_save` come from the table the turn opened with, and a table read
    again mid-turn doesn't change them."""
    tool_trace: list[dict] = field(default_factory=list)
    recalled_lessons: list[dict] = field(default_factory=list)
    ws_root: Any = None
    started: float = 0.0
    turn_text: Any = None
    steers: list = field(default_factory=list)      # read after a batch, and not yet carried by a request (K9b)
    # Set when the turn opens (`_open_turn`), then only read: the model, the budget, the task or lane, the progress
    # policy, how many requests the budget leaves, the system text (with the acceptance checks and the guard), the
    # schemas a provider refused, and the two tool resolvers with those left out.
    adapter: Any = None
    budget: Any = None
    runtime: Any = None
    acceptance_runtime: Any = None
    policy: Any = None
    request_ceiling: int = 0
    system: str = ""
    drops: Any = None
    resolve_tools: ResolveTools | None = None
    resolve_callable: ResolveTools | None = None
    current_request: dict | None = None
    lesson_notes: list[str] = field(default_factory=list)
    research_source_feedback: list = field(default_factory=list)
    mcp_fail_counts: dict[str, int] = field(default_factory=dict)
    mcp_hint_logged: set[str] = field(default_factory=set)
    call_ids: set[str] = field(default_factory=set)
    recovery: Any = None                             # model_call.TurnRecovery
    plan: Any = None                                 # turn_plan.Plan
    own_folder: Any = None
    offline_note: str = ""
    can_save: bool = False
    # The table: read again after a provider refuses a schema (`_request`) and after a card adds a capability
    # (the batch), so a later call of the same batch is checked against the new one.
    wired: list[dict] = field(default_factory=list)
    wired_keys: set[str] = field(default_factory=set)
    schemas: list[dict] = field(default_factory=list)
    params_by_key: dict = field(default_factory=dict)
    convo: list[dict] = field(default_factory=list)  # rebound when the history is fitted (`_fit_history`)
    pending_feedback: int = 0                        # the newest batch's records, delivered whole once
    history_compacted: bool = False
    stop_reason: str | None = None                   # kept from the step that set it to the answer
    # 0.1.50 completion first after a stop (S6 bench, T2): repeated failure ends RESEARCH, not the
    # deliverable. The run enters finish mode once (sticky): up to two steps where only the save tools
    # run (K3: the table stays, other calls are refused), then text only. Without save tools a
    # no-progress stop forces an answer at once, as before. (0.1.63 K4b: a spent web-read allowance
    # no longer starts it; live reads have none.)
    finish_reason: str | None = None
    finish_from: int = 0
    finish_steps: int = 0
    # Wrap-up keeps the FULL tool list (an unchanged list keeps the provider's prompt
    # cache: a narrowed one re-sent ~28k tokens uncached in the S6 bench). K3: it no
    # longer narrows after a refused research call either; refusals say why, and after
    # the second refused call the next step is text only (the same table, tool_choice
    # none), so a model that keeps reaching for research still delivers.
    wrap_refused: int = 0
    long_turn_told: bool = False
    tool_steps: int = 0              # K5: steps whose calls are not only update_plan
    # SMART-5: whether a call so far changed something, and how far that was checked
    work: dict = field(default_factory=lambda: {"done": False, "seen": 0})
    link_hints: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StepMode:
    """What one step may do, worked out at its start (`_step_mode`): forced is text only."""
    forced: bool
    finishing: bool
    saved: bool
    no_progress: bool
    truncation_stop: bool


@dataclass(frozen=True, slots=True)
class StepReply:
    """One step's model reply (`_request`): the response, the step's stream (or None), and its tool calls."""
    resp: Any
    stream: Any
    tool_calls: list


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
