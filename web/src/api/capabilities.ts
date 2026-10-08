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

/** 0.1.57 §4: something Arslan found and kept for later ("Arslan 找到的"). */
export interface CapabilityFind {
  id: string; need: string; why: "declined" | "job" | "project_level";
  conversation_id: string | null; project_id: string | null; level_id: string | null;
  candidate: CapabilityCandidate; created_at: string;
}
/** 0.1.57 §7: the dossier of a capability Arslan installed (or tried to). */
export interface CapabilitySource {
  id: string; kind: "mcp" | "skill"; name: string; candidate_id: string; source_url: string | null; repo: string | null;
  version: string | null; commit_sha: string | null; artifact_sha256: string | null; lock_sha256: string | null;
  license: { spdx: string | null; read_from: string | null }; stars: number | null; pushed_days: number | null;
  checked_at: string | null; runtime: string | null;
  needs: { keys?: { name: string; secret: boolean; required: boolean }[]; network?: boolean | null };
  grants: { folders?: string[]; network?: boolean };
  scan: { level: "clean" | "notes" | "blocked"; findings: { rule: string; level: string; file: string; line: number; excerpt: string }[] } | null;
  test: { ok: boolean; stage?: string; detail?: string; tools?: string[]; at?: string } | null;
  files: Record<string, string> | null; state: "installed" | "failed" | "removed" | "proposed"; error: string | null;
  mcp_server_id: number | null; skill_key: string | null; installed_at: string | null;
}
export interface InstallResult { state: "on" | "failed" | "blocked"; source_id?: string; stage?: string; code?: string;
  detail?: string; tools?: string[]; skill?: string }
export interface UpdateInfo { current: string | null; latest: string | null; newer: boolean; compare_url?: string | null;
  reason?: string; candidate?: CapabilityCandidate | null }

const json = (method: string, body: unknown) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const capabilitiesApi = {
  finds: () => request<CapabilityFind[]>("/capability-finds"),
  dismissFind: (id: string) => request<{ ok: boolean }>(`/capability-finds/${encodeURIComponent(id)}/dismiss`, { method: "POST" }),
  sources: () => request<CapabilitySource[]>("/capability-sources"),
  checkCandidate: (candidateId: string) =>
    request<{ candidate: CapabilityCandidate; installable: boolean; why_not: string | null }>("/capability-candidates/check",
      json("POST", { candidate_id: candidateId })),
  /** "加进能力库": install, scan, test, switch on (the same steps as the card in a conversation). */
  install: (candidateId: string, folders: string[], keys: Record<string, string>) =>
    request<InstallResult>("/capability-candidates/install", json("POST", { candidate_id: candidateId, folders, keys })),
  setFolders: (sourceId: string, folders: string[]) =>
    request<CapabilitySource>(`/capability-sources/${encodeURIComponent(sourceId)}/folders`, json("PUT", { folders })),
  remove: (sourceId: string) => request<{ ok: boolean }>(`/capability-sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" }),
  checkUpdate: (sourceId: string) => request<UpdateInfo>(`/capability-sources/${encodeURIComponent(sourceId)}/update`),
  update: (sourceId: string) => request<InstallResult>(`/capability-sources/${encodeURIComponent(sourceId)}/update`, { method: "POST" }),
  asMaterial: (projectId: string, candidateId: string) =>
    request<{ collection_id: number; chunks: number }>(`/projects/${encodeURIComponent(projectId)}/capability-material`,
      json("POST", { candidate_id: candidateId })),
  /** 0.1.57: what you want done, across the official MCP Registry, GitHub and skill libraries. */
  search: (q: string, kind?: CapabilityCandidate["kind"]) =>
    request<CapabilitySearch>(`/capability-search?q=${encodeURIComponent(q)}${kind ? `&kind=${kind}` : ""}`),
  list: () => request<CapabilityRow[]>("/capabilities"),
  switch: (key: string, on: boolean) => request<CapabilityRow>(`/capabilities/${encodeURIComponent(key).replace(/%3A/g, ":")}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ on }),
  }),
};
