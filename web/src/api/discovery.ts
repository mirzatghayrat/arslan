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

// ── arslan.plugin.json (spec 2026-08-18 Part B): author-shipped config ────────
export type ManifestEnvSlot = { secret: boolean; description: string };
export type ManifestServer = {
  label: string;
  transport: "stdio" | "http";
  command?: string;
  args?: string[];
  url?: string;
  env?: Record<string, ManifestEnvSlot>;
};
export type PluginManifest = {
  schema_version: 1;
  name: string;
  version: string;
  description: string;
  min_app_version: string | null;
  mcp_servers: ManifestServer[];
  skills: string[];
  suggest_spawn_expose: boolean;
};

export type RepoOverview = { what: string; use_cases: string[] };

export type EvalResult = {
  repo: EvalRepo;
  trust: { tier: "high" | "medium" | "low"; license_note: string };
  suggestion: EvalSuggestion;
  /** Plain-language intro for non-programmers; empty {what:"",use_cases:[]} → hide. */
  overview?: RepoOverview;
  /** Author-shipped truth — present only when the repo carries a VALID manifest. */
  manifest?: PluginManifest;
  /** Present only when a manifest exists but is broken; the guess path still runs. */
  manifest_error?: string;
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
  topics: string[];
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

// ── Add as Skill: distill a repo into a SkillPack (generate → editable body → create) ─────
// generateSkill is read-only (persists nothing). The user reviews/edits the body (the
// human-review/consent step), then createSkill persists it as tier=safe/status=registered.

export type SkillDraft = { name: string; category: string; description: string; body: string };
export type SkillGenResult = { repo: { full_name: string; html_url: string }; skill: SkillDraft | null };
export type CreatedSkill = { key: string; name: string; category: string; description: string; tier: string; status: string };

export const generateSkill = (ref: string) =>
  request<SkillGenResult>("/discovery/skill/generate", { method: "POST", body: JSON.stringify({ ref }) });

export const createSkill = (b: { full_name: string; name: string; category: string; description: string; body: string }) =>
  request<CreatedSkill>("/discovery/skill", { method: "POST", body: JSON.stringify(b) });

// ── P3: faithful SKILL.md importer (verbatim; license-gated server-side) ─────────
// Unlike generateSkill (LLM distill/rewrite), scan+import bring standard Agent-Skills
// SKILL.md files in VERBATIM, with bundled scripts/*.py stored for the sandbox.

export type ScannedSkill = {
  path: string;
  key?: string;
  name?: string;
  description?: string;
  body_bytes?: number;
  scripts: string[];
  importable: boolean;
  reason: string | null;
};

export type SkillScanResult = {
  repo: { full_name: string; html_url: string; license: string | null; stars: number };
  license_ok: boolean;
  license_note: string | null;
  skills: ScannedSkill[];
};

export type ImportedSkill = {
  key: string; name: string; description: string; scripts: string[]; license: string | null;
};

export const scanSkills = (ref: string, subpath = "") =>
  request<SkillScanResult>("/discovery/skills/scan", {
    method: "POST", body: JSON.stringify({ ref, subpath }),
  });

export const importSkill = (ref: string, path: string) =>
  request<ImportedSkill>("/discovery/skills/import", {
    method: "POST", body: JSON.stringify({ ref, path }),
  });
