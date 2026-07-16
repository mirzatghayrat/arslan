import { request } from "./client";
import type { McpConnector } from "./client.types";

// ── MCP preset connector catalog ──────────────────────────────────────────────
// Single source of truth (server/mcp/catalog.py) for the Settings recommended list and
// conversation-driven connect. Static, versioned, reviewed data — no client-side fallback.

export const getMcpCatalog = () => request<McpConnector[]>("/mcp/catalog");
