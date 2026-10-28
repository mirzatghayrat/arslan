import type { TFunction } from "i18next";
import { api } from "../api/client";
import { companionApi, type MemoryProposal } from "../api/companion";

/**
 * Everything about memory that waits for the user's OK, from its two sources, as one
 * list (0.1.55 §12/§13 — "等你确认" in the Inbox and at the top of Memory):
 *   - memory entries that wait (sensitive, or written from elsewhere): /memory/proposals
 *   - curation suggestions (merge, supersede, …): /brain/proposals?status=pending
 * Learned practices are not here since v0.1.64 (INB1): one that is not in effect is listed with its
 * reason in Memory's "learned practices", and nothing waits for an OK.
 * Each source fails on its own: one broken endpoint never hides the other.
 */
export interface PendingMemoryItem {
  key: string;
  source: "memory" | "curation";
  text: string;
  sensitive: boolean;
  createdAt: string | null;
  /** Keep it: memory → confirmed, only for local models (sensitive acknowledged); curation → apply. */
  accept: () => Promise<unknown>;
  reject: () => Promise<unknown>;
  /** The memory proposal itself, for the full review dialog (scope, cloud choice, conflicts). */
  proposal?: MemoryProposal;
}

export async function loadPendingMemory(t: TFunction): Promise<PendingMemoryItem[]> {
  const [memory, curation] = await Promise.allSettled([
    companionApi.proposals(), api.listMemoryProposals({ status: "pending", limit: 50 }),
  ]);
  const out: PendingMemoryItem[] = [];
  if (memory.status === "fulfilled") {
    for (const p of memory.value) {
      const sensitive = p.entry.sensitivity !== "normal";
      out.push({
        key: `m:${p.id}`, source: "memory", sensitive, createdAt: p.entry.created_at ?? null, proposal: p,
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
  return out.sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? ""));
}
