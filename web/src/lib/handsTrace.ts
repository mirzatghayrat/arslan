import { ArrowDownUp, Command, Eye, Keyboard, ListChecks, MousePointerClick, type LucideIcon } from "lucide-react";
import { request } from "../api/client";

/** One Hands call as the backend traced it (0.1.53): never typed text, only its length. Since INB7-c4c a run's calls show in its
 *  「诊断」, not in a card of their own. */
export interface HandsTraceEntry {
  at: string;
  app?: string | null;
  op: string;
  outcome: string;
  target?: string | null;
  typed_chars?: number;
  ms?: number;
  /** The conversation the call was made in, or null. */
  conversation?: string | null;
  /** v0.1.64 (#632): the run it was made in; null on older entries and outside a run. */
  run_id?: number | null;
}

export const getHandsTrace = (limit = 100) => request<{ entries: HandsTraceEntry[] }>(`/hands/trace?days=7&limit=${limit}`);

/** 0.1.58 §7: one icon per kind of Hands call; anything that only looks gets the eye. */
export function handsOpIcon(op: string): LucideIcon {
  return ({ click: MousePointerClick, set_value: Keyboard, select: ListChecks, scroll: ArrowDownUp, press: Command } as
    Record<string, LucideIcon>)[op] ?? Eye;
}
