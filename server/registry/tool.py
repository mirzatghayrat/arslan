"""One object per tool (LOOP1 a): its name, what the model reads, its parameters, when it is offered, and what answers
it. A new tool is one `Tool` in a family under `tool_defs`, plus its executor unless the loop answers it itself."""
from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, get_args


@dataclass(frozen=True, slots=True)
class Offer:
    """What decides which tools a turn is offered, built once per table so every predicate sees the same answers.
    `read_offer` makes the reads."""
    in_task: bool
    in_job: bool
    can_ask: bool
    browser: bool               # the managed browser is set up, or only needs its one-time setup
    mac: bool
    hands: bool
    scheduled: bool             # this call is in a scheduled run
    skills: str                 # the index read_skill lists; empty when there are none
    in_project: bool
    default_read: bool          # the file tools and attach_file follow this read of the folder setting
    workspace: bool
    own_folder: bool            # the workspace is Arslan's own folder
    lan: bool
    ssh: bool
    enrolled: bool              # SSH is on and a machine is enrolled
    folders_open: bool          # run_command's words follow this later read of the folder setting
    nobody_to_ask: bool         # a task's turn with no card surface (a scheduled fire, the heartbeat)
    fire: bool                  # ASK1-b: a scheduled task's own fire (command_gate.fire_runs_commands)
    shell: bool
    bottom_layer: bool          # SUB5e: this conversation is a sub-session's sub-session (or its chain can't be read)


async def read_offer(skill_index: Callable[[], Awaitable[str]]) -> Offer:
    """Everything a table depends on. The order is what it has always been, and two answers can't be taken from an
    earlier one: the folder setting has a read for each of its readers, and a task can close during the awaits between
    `in_task` and `nobody_to_ask`, which `task_service.current` also checks."""
    from server.db import session as db_session
    from server.registry import hands_tools
    from server.services import agent_browser, background_jobs, permissions, personal_context, settings_service, task_service
    in_task = task_service.current() is not None
    in_job = background_jobs.inside_job()
    can_ask = permissions.current_asker() is not None
    # In a thread: it looks node and npm up on the user's PATH, which may wait for the login shell (#674 review).
    browser = await asyncio.to_thread(agent_browser.available)
    mac = sys.platform == "darwin"
    hands = hands_tools.desktop_available()
    scheduled = hands_tools._scheduled_run() is not None
    skills = await skill_index()
    context = personal_context.current()
    async with db_session.AsyncSessionLocal() as db:
        workspace = await settings_service.workspace_dir_for_run(db)       # SUB5c: a sub-session's own folder
        default_read = await settings_service.default_read_enabled(db)
        own_folder = await settings_service.workspace_is_default(db)
    async with db_session.AsyncSessionLocal() as db:
        lan = await settings_service.lan_discovery_enabled(db)
    async with db_session.AsyncSessionLocal() as db:
        ssh = await settings_service.ssh_enabled(db)
        enrolled = False
        if ssh:
            from server.services import ssh_nodes
            enrolled = bool(await ssh_nodes.list_nodes(db))
    # 0.1.48 terminal: on unless the user switched it off (terminal_policy decides what runs).
    async with db_session.AsyncSessionLocal() as db:
        # Read again, in this session, for the command's words only: the tools around it keep the first read.
        folders_open = await settings_service.default_read_enabled(db)
        # A turn with nobody to ask runs no command, so none is offered there (the tool loop refuses one anyway),
        # except a scheduled task's own fire (ASK1-b). Outside a turn (the Capabilities page) the list says what a
        # turn is offered.
        nobody_to_ask = task_service.current() is not None and permissions.current_asker() is None
        from server.orchestrator import command_gate
        fire = nobody_to_ask and command_gate.fire_runs_commands(context.conversation_id if context else None)
        shell = await settings_service.shell_enabled(db)
    bottom_layer = await _bottom_layer(context.conversation_id if context is not None else None)
    return Offer(in_task=in_task, in_job=in_job, can_ask=can_ask, browser=browser, mac=mac, hands=hands,
                 scheduled=scheduled, skills=skills, in_project=bool(context is not None and context.project_id),
                 default_read=default_read, workspace=workspace is not None, own_folder=own_folder, lan=lan, ssh=ssh,
                 enrolled=enrolled, folders_open=folders_open, nobody_to_ask=nobody_to_ask, fire=fire, shell=shell,
                 bottom_layer=bottom_layer)


async def _bottom_layer(conversation_id: str | None) -> bool:
    """SUB5e: whether this conversation is on the last layer a sub-session can be (`sub_sessions.MAX_DEPTH`), read from
    the stored chain. One that can't be read counts as the bottom: it is offered no sub-session, as a chain that can't
    be read gets none of the permissions."""
    if not conversation_id:
        return False
    from server.db import session as db_session
    from server.services import sub_sessions
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await sub_sessions.depth(db, conversation_id) >= sub_sessions.MAX_DEPTH
    except Exception:  # noqa: BLE001 — never a reason to fail a turn's table
        return True


def always(_offer: Offer) -> bool:
    return True


Effect = Literal["read", "local_write", "external_write"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Traits:
    """What the code that treats tools differently needs to know about one (LOOP1 a6). Every tool states every trait:
    there are no defaults, so a tool that leaves one out fails when its family is imported. The name sets those modules
    read are derived from these (`tool_defs.named`); a key that isn't a registry tool states its traits in
    `tool_defs.UNLISTED`. MCP tools have none here: each module judges them per call, by name or by their server."""
    effect: Effect      # how task_service.effect_of grades a call by name, which also decides retries. external_write is
    #                     the safe grade for anything not known to be a read or a local write, so a tool may be graded
    #                     more strictly than it acts; run_command's grade comes from its command first.
    parallel: bool      # parallel_reads: runs alongside the reads next to it (no card, no shared state)
    outside: bool       # untrusted.counts_as_external: what it returns is outside content
    saves: bool         # tool_loop.WRAP_UP_TOOLS: saves a job's deliverable, so it may run while the job wraps up

    def __post_init__(self) -> None:
        if self.effect not in get_args(Effect):
            raise ValueError(f"effect {self.effect!r} is not one of {get_args(Effect)}")
        for name in ("parallel", "outside", "saves"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"trait {name} must be True or False, not {getattr(self, name)!r}")


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str | Callable[[Offer], str]   # a callable when the words depend on the turn
    schema: dict
    offered: Callable[[Offer], bool] = always
    host: bool = False          # the tool loop answers it: there is no executor
    # Its own gate, after the common ones (LOOP1 c2): `gate(tool_key, args, turn)` answers with a refusal to record,
    # run_command's plan, or None to go on. In `server/orchestrator/tool_gates.py` and `command_gate.py`.
    gate: Callable[..., Awaitable[object]] | None = None
    traits: Traits = field(kw_only=True)


def listed(tools: Iterable[Tool], offer: Offer) -> list[dict]:
    """The tools this turn is offered, as `_every_tool` lists them. The order is part of the contract: find_tools breaks
    its ties by it."""
    return [{"key": tool.name,
             "description": tool.description(offer) if callable(tool.description) else tool.description}
            for tool in tools if tool.offered(offer)]


def check(tools: Iterable[Tool], executors: dict) -> None:
    """Refuse a table that can't work, when it is built, so it never reaches a turn: a name twice, parameters that aren't
    an object (providers refuse them), or a tool nothing answers."""
    seen: set[str] = set()
    for tool in tools:
        if tool.name in seen:
            raise ValueError(f"tool {tool.name!r} is defined twice")
        seen.add(tool.name)
        if tool.schema.get("type") != "object":
            raise ValueError(f"tool {tool.name!r}: its parameters must be a JSON object schema")
        if tool.host == (tool.name in executors):
            raise ValueError(f"tool {tool.name!r}: it must have an executor or be answered by the loop, not both or neither")


def check_traits(tools: Iterable[Tool], unlisted: Mapping[str, Traits]) -> None:
    """Refuse traits that aren't stated, when the table is built: every tool's, and every key outside the registry
    whose traits are listed once, under a name no tool has."""
    names = set()
    for tool in tools:
        if not isinstance(tool.traits, Traits):
            raise ValueError(f"tool {tool.name!r}: its traits must be a Traits")
        names.add(tool.name)
    for key, traits in unlisted.items():
        if key in names:
            raise ValueError(f"{key!r} is a registry tool: its traits are on its Tool")
        if not isinstance(traits, Traits):
            raise ValueError(f"{key!r}: its traits must be a Traits")
