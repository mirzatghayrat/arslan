import { request } from "./client";

/** One row of GET /capabilities (0.1.55 §14, server/services/capability_list.py). */
export interface CapabilityRow {
  key: string;
  group: "mac" | "work" | "research" | "methods";
  /** on: offered now · off: switched off · setup: one step missing · na: cannot work here */
  state: "on" | "off" | "setup" | "na";
  /** The tool keys this row stands for when it is on. */
  tools: string[];
  /** Which switch governs it; null = no switch (always on, or not switchable). */
  switch: "setting" | "hands" | "mcp" | "skill" | null;
  reason: string | null;
  /** What the one step is: open_settings:<section>, open_tab:<tab>, connect. */
  fix: string | null;
  /** Server-supplied name (MCP label, skill name); built-ins are named by key. */
  name: string | null;
  detail: string | null;
  source: "builtin" | "mcp" | "skill";
}

/** One candidate of GET /capability-search (0.1.57 §2, server/services/capability_search.py). */
export interface CapabilityCandidate {
  id: string;
  kind: "mcp" | "skill" | "project";
  name: string;
  summary: string;
  source: "registry" | "github" | "library";
  source_url: string | null;
  repo: string | null;
  version: string | null;
  /** How it would run here; null with `not_here` when it cannot. */
  runtime: "uv" | "node" | "mcpb" | "remote" | "skill" | null;
  package: { registry_type: string; identifier: string; version: string | null } | null;
  remote: { type: string; url: string } | null;
  not_here: "needs_dotnet" | "needs_docker" | "no_runnable_package" | "nothing_published" | "not_in_registry" | null;
  needs: { keys: { name: string; secret: boolean; required: boolean; description: string }[]; network: boolean | null };
  /** Read at the source: usable · reference_only (only read the idea) · unknown (none found). */
  license: { spdx: string | null; read_from: string | null; verdict: "usable" | "reference_only" | "unknown" };
  stars: number | null;
  pushed_days: number | null;
  checked_at: number | null;
  path: string | null;
}
export interface CapabilitySearch { words: string[]; candidates: CapabilityCandidate[]; notes: string[] }

export const capabilitiesApi = {
  /** 0.1.57: what you want done, across the official MCP Registry, GitHub and skill libraries. */
  search: (q: string, kind?: CapabilityCandidate["kind"]) =>
    request<CapabilitySearch>(`/capability-search?q=${encodeURIComponent(q)}${kind ? `&kind=${kind}` : ""}`),
  list: () => request<CapabilityRow[]>("/capabilities"),
  switch: (key: string, on: boolean) => request<CapabilityRow>(`/capabilities/${encodeURIComponent(key).replace(/%3A/g, ":")}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ on }),
  }),
};
