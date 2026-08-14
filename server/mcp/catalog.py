"""Backend preset MCP-connector catalog — the SINGLE source of truth for both the
Settings recommended list and conversation-driven connect. Static, versioned, reviewed
data ONLY (no runtime network fetch). Ported from web/src/data/mcpPresets.ts (now deleted)
and extended with per-credential prerequisite metadata (description / how-to URL / paid)
so the connect card can disclose requirements BEFORE the user hits a wall.

`requires_path` / `path_placeholder` restore the old mcpPresets.ts `needsPath` /
`pathPlaceholder` fields (Filesystem + Git take a local filesystem path, appended to
`args` by the caller — never a credential, so they stay `one_click` in the
no-env-required sense). `requires_path` is orthogonal to `env`/`one_click`: a
connector can need a path, credentials, both, or neither."""
from __future__ import annotations

# Each connector: env is a list of REQUIRED credentials; empty env == one_click.
# requires_path/path_placeholder gate a local-path prompt independent of env.
#: `auth` is EXPLICIT on every entry — "none" | "static_key" | "oauth" — because the
#: derived two-way split (`_one_click` = "has no env") has no way to say "needs an
#: OAuth flow we do not support yet". The first oauth-shaped entry added under the
#: old shape would have rendered as a needs-key card with a prefill form collecting
#: a key no service will ever issue. The field ships before any oauth entry does,
#: deliberately (ruling ②, 2026-08-08): the mechanism first, never a decoy entry.
CONNECTORS: list[dict] = [
    {"key": "fetch", "auth": "none", "label": "Fetch", "transport": "stdio", "command": "uvx",
     "args": ["mcp-server-fetch"], "url": None, "runtime": "python", "env": [],
     "requires_path": False, "path_placeholder": None,
     "description": "Fetch a URL and convert it to clean markdown."},
    {"key": "memory", "auth": "none", "label": "Memory", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-memory"], "url": None, "runtime": "node",
     "env": [], "requires_path": False, "path_placeholder": None,
     "description": "Persistent knowledge-graph memory (stored locally)."},
    {"key": "sequential-thinking", "auth": "none", "label": "Sequential Thinking", "transport": "stdio",
     "command": "npx", "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
     "url": None, "runtime": "node", "env": [],
     "requires_path": False, "path_placeholder": None,
     "description": "A structured step-by-step reasoning scaffold."},
    {"key": "time", "auth": "none", "label": "Time", "transport": "stdio", "command": "uvx",
     "args": ["mcp-server-time"], "url": None, "runtime": "python", "env": [],
     "requires_path": False, "path_placeholder": None,
     "description": "Current time and timezone conversion."},
    {"key": "filesystem", "auth": "none", "label": "Filesystem", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-filesystem"], "url": None, "runtime": "node",
     "env": [], "requires_path": True, "path_placeholder": "/absolute/path/to/expose",
     "description": "Read and write files under a directory you choose. Takes a local path."},
    {"key": "git", "auth": "none", "label": "Git", "transport": "stdio", "command": "uvx",
     "args": ["mcp-server-git", "--repository"], "url": None, "runtime": "python", "env": [],
     "requires_path": True, "path_placeholder": "/absolute/path/to/git/repo",
     "description": "Read, search, and commit a local git repository. Takes a repo path."},
    {"key": "everything", "auth": "none", "label": "Everything", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-everything"], "url": None, "runtime": "node",
     "env": [], "requires_path": False, "path_placeholder": None,
     "description": "Reference server with sample tools — for testing MCP plumbing."},
    {"key": "brave-search", "auth": "static_key", "label": "Brave Search", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-brave-search"], "url": None, "runtime": "node",
     "requires_path": False, "path_placeholder": None,
     "description": "Web search via the Brave Search API.",
     "env": [{"name": "BRAVE_API_KEY",
              "description": "A Brave Search API key.",
              "get_it_url": "https://brave.com/search/api/",
              "paid": False}]},
    {"key": "github", "auth": "static_key", "label": "GitHub", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-github"], "url": None, "runtime": "node",
     "requires_path": False, "path_placeholder": None,
     "description": "GitHub repo / issue / PR access.",
     "env": [{"name": "GITHUB_PERSONAL_ACCESS_TOKEN",
              "description": "A GitHub personal access token (classic or fine-grained).",
              "get_it_url": "https://github.com/settings/tokens",
              "paid": False}]},
    # Playwright. CONTAINMENT IS IN THE ARGS, not in a note asking the user to
    # be careful: --isolated gives every session a throwaway profile, so the
    # browser starts with no cookies, no logged-in accounts and nothing of the
    # user's own to lose. A connector that could drive a signed-in browser is a
    # different and much larger thing than one that cannot, and which of the two
    # this is must not depend on anybody remembering a flag.
    {"key": "playwright", "auth": "none", "label": "Playwright", "transport": "stdio", "command": "npx",
     "args": ["-y", "@playwright/mcp@latest", "--isolated"], "url": None,
     "runtime": "node", "env": [], "requires_path": False, "path_placeholder": None,
     "description": ("Drive a web page through its accessibility tree — read what is on "
                     "screen, and (once you allow it) click and type. Runs in a private "
                     "browser profile with no logged-in accounts."),
     "containment": "isolated browser profile; no access to your signed-in sessions"},
]

# Manual tiering, because the heuristic is WRONG here and wrong in the unsafe
# direction's opposite: verified on this build, suggest_tier() answers
# "orchestrator" for every playwright tool including browser_snapshot, since
# none of snapshot/click/navigate/type appears in its read or write verb lists.
# A toolset with no safe tool fails assert_assignable, so a spawn would gain
# nothing at all from this connector.
#
# The grading rule is the obvious one, applied by hand: a tool that only OBSERVES
# is safe; a tool that ACTS on the page starts at orchestrator and can be raised
# per tool in Settings. Listing them explicitly rather than pattern-matching
# "read-ish" names is the point — a new tool nobody graded must fall through to
# the conservative default rather than inherit a guess from its name.
PLAYWRIGHT_TOOL_TIERS: dict[str, str] = {
    # observe only
    "browser_snapshot": "safe",
    "browser_take_screenshot": "safe",
    "browser_console_messages": "safe",
    "browser_network_requests": "safe",
    "browser_tabs": "safe",
    # act on the page — deliberately NOT safe
    "browser_click": "orchestrator",
    "browser_type": "orchestrator",
    "browser_fill_form": "orchestrator",
    "browser_navigate": "orchestrator",
    "browser_navigate_back": "orchestrator",
    "browser_press_key": "orchestrator",
    "browser_select_option": "orchestrator",
    "browser_hover": "orchestrator",
    "browser_drag": "orchestrator",
    "browser_file_upload": "orchestrator",
    "browser_evaluate": "orchestrator",
    "browser_handle_dialog": "orchestrator",
    "browser_wait_for": "orchestrator",
    "browser_resize": "orchestrator",
    "browser_close": "orchestrator",
    "browser_install": "orchestrator",
}

# Which connectors carry a hand-graded table. Keyed by the command+args shape a
# server was created from, because MCPServer does not record which preset it
# came from and inventing a column for this would be a migration for a lookup.
MANUAL_TIERS: dict[str, dict[str, str]] = {
    "@playwright/mcp": PLAYWRIGHT_TOOL_TIERS,
}


def manual_tier(server_args: list[str] | None, tool_name: str) -> str | None:
    """A hand-assigned tier, or None when this server is not hand-graded at all.

    ONCE A CONNECTOR IS IN THE TABLE, THE TABLE IS AUTHORITATIVE: an ungraded
    tool from a graded server gets "orchestrator", never the heuristic. That is
    the whole reason the table exists — this connector's names do not mean what
    the verb list thinks they mean, and falling back would hand a future
    `browser_read_*` a "safe" grade purely because it starts with a read verb,
    which is exactly the review this table replaces.

    None still means "not one of the hand-graded connectors", and those keep the
    heuristic they always had."""
    for token in server_args or []:
        for marker, table in MANUAL_TIERS.items():
            if marker in str(token):
                return table.get(tool_name, "orchestrator")
    return None


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
