import type { StoredArtifact } from "../api/client.types";

export const DOCK_KEY = "arslan.work-dock.v1";
export const OPEN_ARTIFACT = "arslan:open-artifact";
export type DockTab = ({ id: string; kind: "browser"; conversationId: string; taskId: string | null; title?: string }
  | { id: string; kind: "artifact"; file: StoredArtifact }) & { temporary?: boolean };

export function validArtifact(value: unknown): value is StoredArtifact {
  if (!value || typeof value !== "object") return false;
  const file = value as StoredArtifact;
  return file.kind === "file" && Number.isSafeInteger(file.run_id) && file.run_id > 0
    && typeof file.filename === "string" && /^[A-Za-z0-9_.-]{1,240}$/.test(file.filename) && !file.filename.includes("..")
    && typeof file.sha256 === "string" && /^[a-f0-9]{64}$/.test(file.sha256)
    && Number.isSafeInteger(file.bytes) && file.bytes >= 0 && file.bytes <= 100 * 1024 * 1024
    && typeof file.title === "string" && file.title.length <= 500 && typeof file.media_type === "string";
}

export function openArtifact(file: StoredArtifact) {
  if (validArtifact(file)) window.dispatchEvent(new CustomEvent(OPEN_ARTIFACT, { detail: file }));
}

export function saveDock(tabs: DockTab[], width: number, temporary: boolean) {
  if (temporary) return;
  // No source text, screenshots, URLs, query tokens, cookies, sessions or form values.
  const safe = tabs.filter(tab => !tab.temporary).slice(0, 8).map(tab => tab.kind === "browser"
    ? { id: tab.id, kind: tab.kind, conversationId: tab.conversationId, taskId: tab.taskId }
    : { id: tab.id, kind: tab.kind, file: { ...tab.file, title: tab.file.filename, url: "" } });
  try { localStorage.setItem(DOCK_KEY, JSON.stringify({ width, tabs: safe })); } catch { /* Storage may be disabled. */ }
}

export function restoreDock(): { tabs: DockTab[]; width: number } {
  try {
    const value = JSON.parse(localStorage.getItem(DOCK_KEY) ?? "null");
    if (!value || !Array.isArray(value.tabs)) return { tabs: [], width: 420 };
    const tabs = value.tabs.slice(0, 8).filter((tab: DockTab) => tab && typeof tab.id === "string" && /^[A-Za-z0-9-]{1,100}$/.test(tab.id)
      && (tab.kind === "artifact" ? validArtifact(tab.file) : tab.kind === "browser" && typeof tab.conversationId === "string"
        && /^[A-Za-z0-9_.:-]{1,100}$/.test(tab.conversationId) && (tab.taskId === null || typeof tab.taskId === "string" && tab.taskId.length <= 200)));
    return { tabs, width: typeof value.width === "number" && Number.isFinite(value.width) ? Math.min(760, Math.max(300, value.width)) : 420 };
  } catch { return { tabs: [], width: 420 }; }
}
