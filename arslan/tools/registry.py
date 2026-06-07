"""ToolRegistry — manages registration and lookup of ArslanTool instances."""
from __future__ import annotations

from arslan.tools.base import ArslanTool


class ToolRegistry:
    """Central registry for Arslan tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ArslanTool] = {}

    def register(self, tool: ArslanTool) -> None:
        """Store tool by its name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ArslanTool | None:
        """Return the tool with the given name, or None if not found."""
        return self._tools.get(name)

    def search_by_tags(self, tags: list[str]) -> list[ArslanTool]:
        """Return tools that match ANY of the provided tags."""
        tag_set = set(tags)
        return [tool for tool in self._tools.values() if tag_set.intersection(tool.tags)]

    def search(self, query: str) -> list[ArslanTool]:
        """Return tools whose name or description contains the query (case-insensitive)."""
        q = query.lower()
        return [
            tool
            for tool in self._tools.values()
            if q in tool.name.lower() or q in tool.description.lower()
        ]

    def list_all(self) -> list[ArslanTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def register_builtins(self) -> None:
        """Import and register the built-in tools."""
        from arslan.tools.builtin.llm_caller import LLMCallerTool
        from arslan.tools.builtin.web_search import WebSearchTool

        self.register(LLMCallerTool())
        self.register(WebSearchTool())
