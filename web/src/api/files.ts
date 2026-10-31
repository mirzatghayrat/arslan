import { useAuthStore } from "../stores/authStore";
import { API_BASE, ApiError, request } from "./client";
import type { StoredArtifact } from "./client.types";

/** 0.1.58 §2–§3: files in Arslan's window (server/api/files.py). */
export interface FolderEntry { name: string; path: string; is_dir: boolean; bytes: number | null; modified: string }
export interface Folder {
  path: string; root: string; crumbs: { name: string; path: string }[];
  entries: FolderEntry[]; total: number; more: boolean;
}
export interface PathStat { path: string; exists: boolean; readable: boolean; is_dir: boolean }
export interface TableSheet { name: string; rows: string[][]; truncated: boolean }
export type ConversationFile = StoredArtifact & { created_at?: string | null; logical_key?: string };

const q = (path: string) => `path=${encodeURIComponent(path)}`;
const json = (body: unknown) => ({ method: "POST", body: JSON.stringify(body) });

async function blob(path: string): Promise<Response> {
  const token = useAuthStore.getState().token;
  const response = await fetch(`${API_BASE}/api/v1${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) {
    let detail: unknown;
    try { detail = (await response.json())?.detail; } catch { /* not JSON */ }
    throw new ApiError(`HTTP ${response.status}`, response.status, detail);
  }
  return response;
}

export interface ConversationChangeTurn {
  run_id: number; at: string | null; undone: boolean;
  paths: { folder: string; path: string; kind: "made" | "edited" | "deleted" }[];
}

/** DIFF1: one line of a change, `[op, old line number, new line number, text]` (server: checkpoints.diff). */
export type ChangeDiffLine = [" " | "-" | "+", number | null, number | null, string];
/** DIFF1: a changed path as lines. `reason` (`too_big`, `not_text`, `copy_changed`) when there are none to show;
 *  `since` when the file changed again after the turn (the diff is still against the file now). */
export interface ChangeDiff {
  reason: "too_big" | "not_text" | "copy_changed" | null; kind: "made" | "edited" | "deleted" | null;
  added: number; removed: number; since: boolean; lines: ChangeDiffLine[];
}

export const filesApi = {
  list: (path: string, offset = 0) => request<Folder>(`/files/list?${q(path)}&offset=${offset}`),
  /** The file's bytes, typed by the caller — the server always sends an opaque attachment. */
  read: async (path: string) => new Blob([await (await blob(`/files/read?${q(path)}`)).arrayBuffer()]),
  stat: (paths: string[]) => request<{ items: PathStat[] }>("/files/stat", json({ paths })),
  table: (path: string) => request<{ sheets: TableSheet[] }>(`/files/table?${q(path)}`),
  html: (path: string) => request<{ html: string }>(`/files/html?${q(path)}`),
  pdfPage: async (path: string, page: number) => {
    const r = await blob(`/files/pdf-page?${q(path)}&page=${page}`);
    return { image: new Blob([await r.arrayBuffer()], { type: "image/png" }), pages: Number(r.headers.get("X-Page-Count") ?? "0") };
  },
  open: (path: string) => request<{ ok: boolean }>("/files/open", json({ path })),
  reveal: (path: string) => request<{ ok: boolean }>("/files/reveal", json({ path })),
  home: (conversationId?: string) => request<{ path: string | null; project: { id: string; name: string } | null }>(
    `/files/home${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""}`),
  /** WB1-3: what each turn of this conversation changed in the user's folders, newest first; only turns
   *  that can still be undone (server: GET /conversations/{id}/changes). */
  changes: (conversationId: string) =>
    request<{ turns: ConversationChangeTurn[] }>(`/conversations/${encodeURIComponent(conversationId)}/changes`),
  /** DIFF1: one path a turn changed, as lines (server: GET /conversations/{id}/changes/{run}/diff). */
  changeDiff: (conversationId: string, runId: number, folder: string, path: string) =>
    request<ChangeDiff>(`/conversations/${encodeURIComponent(conversationId)}/changes/${runId}/diff?`
      + `folder=${encodeURIComponent(folder)}&${q(path)}`),
  conversationFiles: (conversationId: string) =>
    request<{ files: ConversationFile[] }>(`/conversations/${encodeURIComponent(conversationId)}/files`),
};
