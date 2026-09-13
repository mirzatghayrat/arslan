import { request } from "./client";
import type { StoredArtifact } from "./client.types";

export interface BrowserState { ready: boolean; reason: string | null; version: string }
export interface BrowserVisit {
  run_id: number; status: string; artifacts: StoredArtifact[];
  result: { url: string; text: string; blocked_connections: number; transfer_bytes: number } | null;
}
export const browserApi = {
  status: () => request<BrowserState>("/browser/status"),
  setup: () => request<BrowserState>("/browser/setup", { method: "POST" }),
  start: (url: string, request_key: string) => request<{ run_id: number }>("/browser/visits",
    { method: "POST", body: JSON.stringify({ url, request_key }) }),
  visit: (id: number) => request<BrowserVisit>(`/browser/visits/${id}`),
};
