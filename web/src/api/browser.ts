import { request } from "./client";
import type { StoredArtifact } from "./client.types";

export interface BrowserState { ready: boolean; reason: string | null; version: string }
export interface BrowserVisit {
  run_id: number; status: string; artifacts: StoredArtifact[];
  result: { url: string; text: string; blocked_connections: number; transfer_bytes: number } | null;
}
export interface ReaderFrame {
  session_id: string; conversation_id: string; task_id: string | null; revision: number;
  title: string; url: string; text: string; screenshot: string;
  links: { id: string; label: string; url: string }[];
  can_back: boolean; can_forward: boolean; blocked_connections: number;
  mode: "isolated_read_only";
}
export type ReaderAction = { action: "navigate"; url: string } | { action: "link"; link_id: string; revision: number }
  | { action: "scroll"; direction: -1 | 1 } | { action: "back" | "forward" | "refresh" };
export const browserApi = {
  status: () => request<BrowserState>("/browser/status"),
  setup: () => request<BrowserState>("/browser/setup", { method: "POST" }),
  start: (url: string, request_key: string) => request<{ run_id: number }>("/browser/visits",
    { method: "POST", body: JSON.stringify({ url, request_key }) }),
  visit: (id: number) => request<BrowserVisit>(`/browser/visits/${id}`),
  createReader: (conversation_id: string, task_id: string | null) => request<{ session_id: string }>("/browser/sessions",
    { method: "POST", body: JSON.stringify({ conversation_id, task_id }) }),
  readerAction: (id: string, action: ReaderAction) => request<ReaderFrame>(`/browser/sessions/${encodeURIComponent(id)}/actions`,
    { method: "POST", body: JSON.stringify(action) }),
  closeReader: (id: string) => request<void>(`/browser/sessions/${encodeURIComponent(id)}`, { method: "DELETE", keepalive: true }),
};
