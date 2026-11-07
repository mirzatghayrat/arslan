"""One object per tool (LOOP1 a): its name, what the model reads, its parameters, when it is offered, and what answers
it. A new tool is one `Tool` in a family under `tool_defs`, plus its executor unless the loop answers it itself."""
from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass


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
    nobody_to_ask: bool         # a task's turn with no card surface (a scheduled run). DELETE-BY: as at its read
    shell: bool


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
        workspace = await settings_service.workspace_dir(db)
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
        # v0.1.63 (the user's decision until S2a-3 lands): a turn with nobody to ask (a scheduled run) runs no
        # command, so none is offered there; the tool loop refuses one anyway. Outside a turn (the Capabilities
        # page) the list says what a turn is offered. DELETE-BY: v0.1.64, with S2a-3 and PR4 (scheduled runs get
        # read-only commands back).
        nobody_to_ask = task_service.current() is not None and permissions.current_asker() is None
        shell = await settings_service.shell_enabled(db)
    return Offer(in_task=in_task, in_job=in_job, can_ask=can_ask, browser=browser, mac=mac, hands=hands,
                 scheduled=scheduled, skills=skills, in_project=bool(context is not None and context.project_id),
                 default_read=default_read, workspace=workspace is not None, own_folder=own_folder, lan=lan, ssh=ssh,
                 enrolled=enrolled, folders_open=folders_open, nobody_to_ask=nobody_to_ask, shell=shell)


def always(_offer: Offer) -> bool:
    return True


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str | Callable[[Offer], str]   # a callable when the words depend on the turn
    schema: dict
    offered: Callable[[Offer], bool] = always
    host: bool = False          # the tool loop answers it: there is no executor


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
