"""Built-in LLMCallerTool — delegates text generation to the runtime LLM."""
from __future__ import annotations

from arslan.tools.base import ArslanTool, ToolResult


class LLMCallerTool(ArslanTool):
    """Generate text content using a language model."""

    name = "llm-caller"
    description = "Generate text content using a language model"
    tags = ["llm", "text-generation", "content"]
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The prompt to send to the LLM"},
            "system": {"type": "string", "description": "Optional system message"},
            "temperature": {
                "type": "number",
                "description": "Sampling temperature (0.0–1.0)",
                "minimum": 0.0,
                "maximum": 1.0,
            },
        },
        "required": ["prompt"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Generated text"},
        },
    }

    async def execute(self, params: dict) -> ToolResult:
        prompt = params.get("prompt")
        if not prompt:
            return ToolResult(success=False, error="Missing required parameter: prompt")
        return ToolResult(
            success=True,
            data={"note": "LLM call delegated to runtime", "prompt_received": prompt},
        )

    async def health_check(self) -> bool:
        return True
