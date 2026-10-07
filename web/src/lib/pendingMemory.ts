import type { TFunction } from "i18next";
import { api } from "../api/client";
import { companionApi } from "../api/companion";
import { lessonsApi } from "../api/lessons";

/**
 * Everything about memory that waits for the user's OK, from its three sources, as one
 * list (0.1.55 §12/§13 — "等你确认" in the Inbox and at the top of Memory):
 *   - memory entries that wait (sensitive, or written from elsewhere): /memory/proposals
 *   - curation suggestions (merge, supersede, …): /brain/proposals?status=pending
 *   - learned practices that wait: /lessons, status "proposed"
 * Each source fails on its own: one broken endpoint never hides the other two.
 */
export interface PendingMemoryItem {
  key: string;
  source: "memory" | "curation" | "lesson";
  text: string;
  sensitive: boolean;
  createdAt: string | null;
  /** Keep it: memory → confirmed, only for local models (sensitive acknowledged); curation → apply; lesson → use. */
  accept: () => Promise<unknown>;
  reject: () => Promise<unknown>;
}

export async function loadPendingMemory(t: TFunction): Promise<PendingMemoryItem[]> {
  const [memory, curation, lessons] = await Promise.allSettled([
    companionApi.proposals(), api.listMemoryProposals({ status: "pending", limit: 50 }), lessonsApi.list(),
  ]);
  const out: PendingMemoryItem[] = [];
  if (memory.status === "fulfilled") {
    for (const p of memory.value) {
      const sensitive = p.entry.sensitivity !== "normal";
      out.push({
        key: `m:${p.id}`, source: "memory", sensitive, createdAt: p.entry.created_at ?? null,
        text: p.candidate?.content ?? p.entry.content ?? "",
        // Kept for local models only: the safe default for something that waited.
        accept: () => companionApi.resolveProposal(p.id, true, sensitive, false),
        reject: () => companionApi.resolveProposal(p.id, false, false, false),
      });
    }
  }
  if (curation.status === "fulfilled") {
    for (const p of curation.value) {
      out.push({
        key: `c:${p.id}`, source: "curation", sensitive: false, createdAt: p.created_at,
        text: p.reason || p.new_excerpt || t("pendingMemory.curationFallback"),
        accept: () => api.acceptMemoryProposal(p.id), reject: () => api.dismissMemoryProposal(p.id),
      });
    }
  }
  if (lessons.status === "fulfilled") {
    for (const l of lessons.value.filter((x) => x.status === "proposed")) {
      out.push({
        key: `l:${l.id}`, source: "lesson", sensitive: false, createdAt: l.created_at, text: l.text,
        accept: () => lessonsApi.setStatus(l.id, "active"), reject: () => lessonsApi.setStatus(l.id, "archived"),
      });
    }
  }
  return out.sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? ""));
}
