import { request } from "./client";

/** One row of GET /capabilities (0.1.55 §14, server/services/capability_list.py). */
export interface CapabilityRow {
  key: string;
  /** v0.1.64 CAP3a: the page's three groups. */
  section: "builtin" | "skills" | "connections";
  /** built in · installed (by you, or from a card) · authored (written by Arslan) · manual (a connection you added) */
  origin: "builtin" | "installed" | "authored" | "manual";
  /** Only what is not built in; the server refuses the rest too (DELETE /capabilities/{key}). */
  deletable: boolean;
  /** When it was last used, from the run records; null: not used yet. */
  last_used: string | null;
  /** The capability source of what was installed from a card (its dossier). */
  source_id: string | null;
  /** A professional method's version (`method:<key>` rows). */
  revision?: number;
  /** on: offered now · off: switched off · setup: one step missing · na: cannot work here */
  state: "on" | "off" | "setup" | "na";
  /** The tool keys this row stands for when it is on. */
  tools: string[];
  /** Which switch governs it; null = no switch (always on, or not switchable). */
  switch: "setting" | "hands" | "mcp" | "skill" | null;
  reason: string | null;
  /** What the one step is: open_settings:<section>, open_tab:<tab>, connect. */
  fix: string | null;
  /** Server-supplied name (MCP label, skill name, a revised method's); built-ins are named by key. */
  name: string | null;
  detail: string | null;
}

/** A candidate as server/services/capability_search.py returns it (0.1.57 §2): here, a newer version in an update check. */
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
  sources: () => request<CapabilitySource[]>("/capability-sources"),
  setFolders: (sourceId: string, folders: string[]) =>
    request<CapabilitySource>(`/capability-sources/${encodeURIComponent(sourceId)}/folders`, json("PUT", { folders })),
  remove: (sourceId: string) => request<{ ok: boolean }>(`/capability-sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" }),
  checkUpdate: (sourceId: string) => request<UpdateInfo>(`/capability-sources/${encodeURIComponent(sourceId)}/update`),
  update: (sourceId: string) => request<InstallResult>(`/capability-sources/${encodeURIComponent(sourceId)}/update`, { method: "POST" }),
  source: (sourceId: string) => request<CapabilitySource>(`/capability-sources/${encodeURIComponent(sourceId)}`),
  list: () => request<CapabilityRow[]>("/capabilities"),
  switch: (key: string, on: boolean) => request<CapabilityRow>(`/capabilities/${rowPath(key)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ on }),
  }),
  /** v0.1.64 CAP3a: delete one row (only a `deletable` one; the server refuses the rest). */
  deleteRow: (key: string) => request<{ ok: boolean }>(`/capabilities/${rowPath(key)}`, { method: "DELETE" }),
};

function rowPath(key: string): string {
  return encodeURIComponent(key).replace(/%3A/g, ":");
}
