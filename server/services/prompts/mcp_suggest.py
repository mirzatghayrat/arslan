"""Prompt: is this GitHub repo an MCP server, and how do you run it?"""
from __future__ import annotations

MCP_SUGGEST_SYSTEM = (
    "You are given a GitHub repo's metadata and README. Decide whether it is a Model Context "
    "Protocol (MCP) server, and if so how to launch it as one. Look for an install/run command in "
    "the README (e.g. `npx -y @scope/server-x`, `uvx mcp-server-x`, `python -m x`) or a hosted "
    "HTTP/streamable endpoint. Respond with ONLY a JSON object: "
    "{\"is_mcp\": true|false, \"transport\": \"stdio\"|\"http\"|null, \"command\": \"<exe like npx>\"|null, "
    "\"args\": [\"...\"], \"url\": \"<http endpoint>\"|null, \"reason\": \"<one short sentence>\"}. "
    "For stdio, put the executable in command and the rest in args (e.g. command=\"npx\", "
    "args=[\"-y\",\"@scope/server-x\"]). When unsure, return is_mcp=false."
)
