"""Built-in WebSearchTool — placeholder for web search capability."""
from __future__ import annotations

from arslan.tools.base import ArslanTool, ToolResult


class WebSearchTool(ArslanTool):
    """Search the web for information on any topic."""

    name = "web-search"
    description = "Search the web for information on any topic"
    tags = ["search", "web", "research"]
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "num_results": {
                "type": "integer",
                "description": "Number of results to return",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of search result objects",
            },
        },
    }

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query")
        if not query:
            return ToolResult(success=False, error="Missing required parameter: query")
        return ToolResult(
            success=True,
            data={"note": "Web search placeholder", "query_received": query, "results": []},
        )

    async def health_check(self) -> bool:
        return True
