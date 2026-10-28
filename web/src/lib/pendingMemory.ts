import type { TFunction } from "i18next";
import { api } from "../api/client";
import { companionApi, type MemoryProposal } from "../api/companion";

/**
 * Everything about memory that was not remembered directly, from its two sources, as one list: Memory's
 * "To sort" (v0.1.64, INB2; it left the Inbox, and nothing here is pushed or counted in the badge):
 *   - memory entries that wait (sensitive, written in a conversation that read outside content, or with
 *     nobody present, …): /memory/proposals
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
  /** A memory entry's proposal says why it waits (INB2): sensitive / external_seen / not_present, or
   *  confirmation_required for the rest, including every one from before v0.1.64. */
  reason?: string;
  createdAt: string | null;
  /** Keep it: memory → confirmed, only for local models (sensitive acknowledged); curation → apply. */
  accept: () => Promise<unknown>;
  reject: () => Promise<unknown>;
  /** The memory proposal itself, for the full review dialog (scope, cloud choice, conflicts). */
  proposal?: MemoryProposal;
}

const PAGE = 100;            // what /memory/proposals returns per call
const MAX_ROWS = 2000;       // a backstop against a source that never says it is done

/** Every row, page by page (#475 review): "To sort" lists all that wait, not the first page. */
async function allPages<T>(page: (offset: number) => Promise<T[]>): Promise<T[]> {
  const out: T[] = [];
  for (let offset = 0; offset < MAX_ROWS; offset += PAGE) {
    const rows = await page(offset);
    out.push(...rows);
    if (rows.length < PAGE) break;
  }
  return out;
}

export async function loadPendingMemory(t: TFunction): Promise<PendingMemoryItem[]> {
  const [memory, curation] = await Promise.allSettled([
    allPages((offset) => companionApi.proposals(offset)),
    allPages((offset) => api.listMemoryProposals({ status: "pending", limit: PAGE, offset })),
  ]);
  const out: PendingMemoryItem[] = [];
  if (memory.status === "fulfilled") {
    for (const p of memory.value) {
      const sensitive = p.entry.sensitivity !== "normal";
      out.push({
        key: `m:${p.id}`, source: "memory", sensitive, reason: p.reason, createdAt: p.entry.created_at ?? null, proposal: p,
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
