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
  conversationFiles: (conversationId: string) =>
    request<{ files: ConversationFile[] }>(`/conversations/${encodeURIComponent(conversationId)}/files`),
};
