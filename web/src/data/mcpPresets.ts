// Prefill payload for the MCP add-form and the Recommended one-click list. `envKeys` present ⇒
// needs credentials ⇒ prefill-only (never one-click). `needsPath` ⇒ credential-free but takes a
// local path arg. `runtime` drives a node/python(uv) hint. `test` marks the reference server.
export type McpPrefill = {
  label: string; command: string; args: string[]; transport: string; url?: string;
  envKeys?: string[]; note?: string; description?: string;
  needsPath?: boolean; pathPlaceholder?: string; runtime?: 'node' | 'python'; test?: boolean;
};

/** A curated preset is one-click-connectable only when it needs no credentials (no envKeys). */
export const isOneClick = (p: McpPrefill): boolean => !(p.envKeys && p.envKeys.length > 0);

// Curated MCP servers (from the official modelcontextprotocol/servers reference set + two
// credentialed favourites). Nothing is installed by default.
//   • no `envKeys`            → one-click: add + connect in a single action.
//   • `needsPath`             → one-click but takes a local path (asked for inline).
//   • `envKeys` present       → needs credentials → prefill the add form (never auto-connect).
//   • `runtime`               → 'node' launches via npx, 'python' via uvx (needs `uv`).
// Commands verified against each server's README (TS servers = npx, Python servers = uvx).
export const MCP_PRESETS: McpPrefill[] = [
  // ── One-click, no credentials ──
  { label: "Fetch", transport: "stdio", command: "uvx", args: ["mcp-server-fetch"],
    runtime: "python", description: "Fetch a URL and convert it to clean markdown." },
  { label: "Memory", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-memory"],
    runtime: "node", description: "Persistent knowledge-graph memory (stored locally)." },
  { label: "Sequential Thinking", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-sequential-thinking"],
    runtime: "node", description: "A structured step-by-step reasoning scaffold." },
  { label: "Time", transport: "stdio", command: "uvx", args: ["mcp-server-time"],
    runtime: "python", description: "Current time and timezone conversion." },
  // ── One-click, needs a local path ──
  { label: "Filesystem", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-filesystem"],
    runtime: "node", needsPath: true, pathPlaceholder: "/absolute/path/to/expose",
    description: "Read and write files under a directory you choose." },
  { label: "Git", transport: "stdio", command: "uvx", args: ["mcp-server-git", "--repository"],
    runtime: "python", needsPath: true, pathPlaceholder: "/absolute/path/to/git/repo",
    description: "Read, search, and commit a local git repository." },
  // ── Test / reference ──
  { label: "Everything", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-everything"],
    runtime: "node", test: true,
    description: "Reference server with sample tools — for testing the MCP plumbing." },
  // ── Needs an API key / token → prefill the add form, never auto-connect ──
  { label: "Brave Search", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-brave-search"], envKeys: ["BRAVE_API_KEY"],
    runtime: "node", description: "Web search via the Brave Search API (needs a Brave API key)." },
  { label: "GitHub", transport: "stdio", command: "npx",
    args: ["-y", "@modelcontextprotocol/server-github"], envKeys: ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    runtime: "node", description: "GitHub repo / issue / PR access (needs a personal access token)." },
];
