"""Backend preset MCP-connector catalog — the SINGLE source of truth for both the
Settings recommended list and conversation-driven connect. Static, versioned, reviewed
data ONLY (no runtime network fetch). Ported from web/src/data/mcpPresets.ts (now deleted)
and extended with per-credential prerequisite metadata (description / how-to URL / paid)
so the connect card can disclose requirements BEFORE the user hits a wall."""
from __future__ import annotations

# Each connector: env is a list of REQUIRED credentials; empty env == one_click.
CONNECTORS: list[dict] = [
    {"key": "fetch", "label": "Fetch", "transport": "stdio", "command": "uvx",
     "args": ["mcp-server-fetch"], "url": None, "runtime": "python", "env": [],
     "description": "Fetch a URL and convert it to clean markdown."},
    {"key": "memory", "label": "Memory", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-memory"], "url": None, "runtime": "node",
     "env": [], "description": "Persistent knowledge-graph memory (stored locally)."},
    {"key": "sequential-thinking", "label": "Sequential Thinking", "transport": "stdio",
     "command": "npx", "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
     "url": None, "runtime": "node", "env": [],
     "description": "A structured step-by-step reasoning scaffold."},
    {"key": "time", "label": "Time", "transport": "stdio", "command": "uvx",
     "args": ["mcp-server-time"], "url": None, "runtime": "python", "env": [],
     "description": "Current time and timezone conversion."},
    {"key": "filesystem", "label": "Filesystem", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-filesystem"], "url": None, "runtime": "node",
     "env": [], "description": "Read and write files under a directory you choose. Takes a local path."},
    {"key": "git", "label": "Git", "transport": "stdio", "command": "uvx",
     "args": ["mcp-server-git", "--repository"], "url": None, "runtime": "python", "env": [],
     "description": "Read, search, and commit a local git repository. Takes a repo path."},
    {"key": "everything", "label": "Everything", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-everything"], "url": None, "runtime": "node",
     "env": [], "description": "Reference server with sample tools — for testing MCP plumbing."},
    {"key": "brave-search", "label": "Brave Search", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-brave-search"], "url": None, "runtime": "node",
     "description": "Web search via the Brave Search API.",
     "env": [{"name": "BRAVE_API_KEY",
              "description": "A Brave Search API key.",
              "get_it_url": "https://brave.com/search/api/",
              "paid": False}]},
    {"key": "github", "label": "GitHub", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-github"], "url": None, "runtime": "node",
     "description": "GitHub repo / issue / PR access.",
     "env": [{"name": "GITHUB_PERSONAL_ACCESS_TOKEN",
              "description": "A GitHub personal access token (classic or fine-grained).",
              "get_it_url": "https://github.com/settings/tokens",
              "paid": False}]},
]


def _one_click(c: dict) -> bool:
    return not c["env"]


def list_connectors() -> list[dict]:
    return [{**c, "one_click": _one_click(c)} for c in CONNECTORS]


def find_connector(query: str) -> dict | None:
    """Case-insensitive exact match on key or label (deterministic; no LLM, no network).
    A fuzzy/aliased 'connect my github' is normalized by the caller to 'github' before this."""
    q = (query or "").strip().lower()
    if not q:
        return None
    for c in CONNECTORS:
        if q == c["key"].lower() or q == c["label"].lower():
            return {**c, "one_click": _one_click(c)}
    return None
