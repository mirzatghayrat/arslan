"""One object per tool (LOOP1 a): its name, what the model reads, its parameters, when it is offered, and what answers
it. A new tool is one `Tool` in a family under `tool_defs`, plus its executor unless the loop answers it itself."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Offer:
    """What decides which tools a turn is offered. Read once per table, so every predicate sees the same turn:
    `read_offer` reads the turn, and `_every_tool` adds the settings where it has always read them."""
    in_task: bool
    in_job: bool
    can_ask: bool
    skills: str = ""            # the index read_skill lists; empty when there are none
    in_project: bool = False
    default_read: bool = False
    workspace: bool = False
    own_folder: bool = False    # the workspace is Arslan's own folder
    lan: bool = False
    ssh: bool = False
    enrolled: bool = False      # SSH is on and a machine is enrolled


def read_offer() -> Offer:
    from server.services import background_jobs, permissions, task_service
    return Offer(in_task=task_service.current() is not None, in_job=background_jobs.inside_job(),
                 can_ask=permissions.current_asker() is not None)


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
