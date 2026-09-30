import { request } from "./client";

// 0.1.48: Arslan's working folder, for the task panel.
export interface WorkspaceFile { path: string; name: string; bytes: number; modified: string }
export interface WorkspaceInfo { path: string; is_default: boolean; recent: WorkspaceFile[] }

const post = (body?: unknown) => ({ method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
export const workspaceApi = {
  get: () => request<WorkspaceInfo>("/workspace"),
  open: (path: string) => request<{ ok: boolean }>("/workspace/open", post({ path })),
  reveal: (path?: string) => request<{ ok: boolean }>("/workspace/reveal", post(path ? { path } : undefined)),
};
