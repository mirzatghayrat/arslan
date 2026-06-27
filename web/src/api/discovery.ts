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

// ── GitHub search + persistent Saved Candidates catalog (read-only browse) ─────
// search → evaluate (reuse evaluateRepo) → save snapshot to catalog → refresh/delete.
// "Add as MCP server" still goes through the P2b addMcpServer path, not here.

export type SearchItem = {
  full_name: string;
  html_url: string;
  stars: number;
  forks: number;
  license: string | null;
  pushed_days: number | null;
  description: string;
  trust: { tier: "high" | "medium" | "low"; license_note: string };
};

export type Candidate = {
  id: number;
  full_name: string;
  html_url: string;
  snapshot: EvalResult;
  saved_at: string;
};

export const searchRepos = (q: string) =>
  request<SearchItem[]>(`/discovery/search?q=${encodeURIComponent(q)}`);

export const saveCandidate = (snapshot: EvalResult) =>
  request<Candidate>("/discovery/catalog", { method: "POST", body: JSON.stringify({ snapshot }) });

export const listCandidates = () =>
  request<Candidate[]>("/discovery/catalog");

export const refreshCandidate = (id: number) =>
  request<Candidate>(`/discovery/catalog/${id}/refresh`, { method: "POST" });

export const deleteCandidate = (id: number) =>
  request<void>(`/discovery/catalog/${id}`, { method: "DELETE" });
