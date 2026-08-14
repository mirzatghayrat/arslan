import { request } from "./client";
import type { McpServer, McpTool } from "./client.types";

// ── MCP servers config + connect/expose/wire ──────────────────────────────────
// Uses the shared `request<T>(path, init)` fetch helper (auth header + ApiError).

export const listMcpServers = () => request<McpServer[]>("/mcp/servers");

export const addMcpServer = (body: {
  label: string;
  command?: string;
  args: string[];
  env: Record<string, string>;
  transport?: string;
  url?: string;
}) =>
  request<McpServer>("/mcp/servers", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const connectMcpServer = (id: number) =>
  request<McpTool[]>(`/mcp/servers/${id}/connect`, { method: "POST" });

export const listMcpTools = (id: number) =>
  request<McpTool[]>(`/mcp/servers/${id}/tools`);

export const exposeMcpServer = (id: number, exposed: boolean) =>
  request<{ ok: boolean }>(`/mcp/servers/${id}/expose`, {
    method: "PATCH",
    body: JSON.stringify({ exposed }),
  });

export const wireMcpTool = (key: string, tier: string, wired: boolean) =>
  request<{ ok: boolean }>(`/mcp/tools/${encodeURIComponent(key)}/wire`, {
    method: "PATCH",
    body: JSON.stringify({ tier, wired }),
  });

export const setMcpToolHost = (key: string, enabled: boolean) =>
  request<{ ok: boolean }>(`/mcp/tools/${encodeURIComponent(key)}/host`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });

export const reconnectMcpServer = (id: number) =>
  request<{ ok: boolean }>(`/mcp/servers/${id}/reconnect`, { method: "POST" });

export const deleteMcpServer = (id: number) =>
  request<{ ok: boolean }>(`/mcp/servers/${id}`, { method: "DELETE" });

/** Kick the interactive OAuth flow; the shell must open the returned URL.
 * Provenance rule (③A): this URL travels backend → here → open_external and
 * nothing else may mint one. */
export const authorizeMcpOauth = (id: number) =>
  request<{ auth_url: string }>(`/mcp/servers/${id}/oauth/authorize`, { method: "POST" });

export const getMcpOauthStatus = (id: number) =>
  request<{ state: "idle" | "waiting" | "done" | "error"; error: string }>(
    `/mcp/servers/${id}/oauth/status`,
  );
