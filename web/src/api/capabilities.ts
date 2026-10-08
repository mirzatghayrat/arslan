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

export const capabilitiesApi = {
  list: () => request<CapabilityRow[]>("/capabilities"),
  switch: (key: string, on: boolean) => request<CapabilityRow>(`/capabilities/${encodeURIComponent(key).replace(/%3A/g, ":")}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ on }),
  }),
};
