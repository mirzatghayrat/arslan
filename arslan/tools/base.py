"""ArslanTool abstract base class and ToolResult."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Result returned by any tool execution."""

    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ArslanTool(ABC):
    """Abstract base class for all Arslan tools."""

    # Class-level attributes — subclasses override these
    name: str = ""
    description: str = ""
    tags: list[str] = []
    input_schema: dict = {}
    output_schema: dict = {}

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """Execute the tool with the given parameters."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the tool is operational."""

    def metadata(self) -> dict:
        """Return a dict describing this tool."""
        return {
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }
