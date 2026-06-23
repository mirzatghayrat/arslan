"""Registry of optimizable fields on a spawn (EvoAgentX-style ParamRegistry).

Registers 'system_prompt' today; the get/set seam lets the evolution loop read
and write the optimizable target without hardcoding attribute access, so future
fields can be added without touching optimizer/promote code.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ParamRegistry:
    def __init__(self) -> None:
        self._fields: dict[str, dict[str, Callable]] = {}

    def register(self, name: str, *, get: Callable[[Any], Any], set: Callable[[Any, Any], None]) -> None:
        self._fields[name] = {"get": get, "set": set}

    def get(self, name: str, spawn: Any) -> Any:
        return self._fields[name]["get"](spawn)

    def set(self, name: str, spawn: Any, value: Any) -> None:
        self._fields[name]["set"](spawn, value)

    def fields(self) -> list[str]:
        return list(self._fields)


def _set_system_prompt(spawn: Any, value: Any) -> None:
    spawn.system_prompt = value


DEFAULT_REGISTRY = ParamRegistry()
DEFAULT_REGISTRY.register(
    "system_prompt",
    get=lambda s: s.system_prompt,
    set=_set_system_prompt,
)
