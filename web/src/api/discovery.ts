import { request } from "./client";

// ── Read-only discovery layer (POST /discovery/evaluate, persists nothing) ─────
// "Add as MCP server" goes through the existing P2b addMcpServer path, not here.

export type EvalRepo = {
  full_name: string;
  html_url: string;
  stars: number;
  forks: number;
  license: string | null;
  pushed_days: number | null;
  description: string;
  topics: string[];
};

export type EvalSuggestion = {
  is_mcp: boolean;
  transport: "stdio" | "http" | null;
  command: string | null;
  args: string[];
  url: string | null;
  reason: string;
};

export type EvalResult = {
  repo: EvalRepo;
  trust: { tier: "high" | "medium" | "low"; license_note: string };
  suggestion: EvalSuggestion;
};

export const evaluateRepo = (ref: string) =>
  request<EvalResult>("/discovery/evaluate", { method: "POST", body: JSON.stringify({ ref }) });
