import type { TFunction } from "i18next";
import { ApiError } from "../api/client";
import type { ProactiveEvidence, ProactiveItem } from "../api/proactive";
import { utcIso } from "./conversationMeta";
import { formatUiDateTime } from "./localeFormatting";
import { isolate } from "./outsideText";

/** Q7 (the user, "as recommended"; ⓪Plan's reading, 2026-11-01): how many days a handled reminder keeps its row, by kind: the
 *  server's FRESH_DAYS (arslan/proactive_policy.py), counted from when it was made. */
export const KEPT_DAYS: Record<string, number> = { job_followup: 7, scheduled_problem: 14, web_change: 14, folder_change: 14, brief: 2 };
const OPEN_STATUSES = new Set(["new", "seen"]);
/** Open: new or seen. Only an open reminder carries a dot. */
export const isOpen = (item: Pick<ProactiveItem, "status">) => OPEN_STATUSES.has(item.status);

/** Q7: a reminder keeps its own row, with its state and no dot, when it is set aside (for as long as that lasts, past its kind's
 *  days too) or handled (Started, Dismissed) within its kind's days; an open one always has its row; an expired one has none. */
export function hasRow(item: Pick<ProactiveItem, "status" | "kind" | "created_at">, now = Date.now()): boolean {
  if (isOpen(item) || item.status === "snoozed") return true;
  if (item.status !== "accepted" && item.status !== "dismissed") return false;
  return Date.parse(utcIso(item.created_at)) > now - (KEPT_DAYS[item.kind] ?? 7) * 86_400_000;
}

/** One line of "why": `text` is the sentence; `quote` is text that came from outside (a page, a
 * file name, an earlier request) and is only ever shown, in quotation marks. */
export interface EvidenceLine { key: string; text: string; quote?: string }

const countOf = (params: Record<string, unknown>) => (typeof params.count === "number" ? { count: params.count } : {});
/** A param is outside text (a watch's label, a task's name, a page's line): isolated, so bidi controls in it cannot reorder the
 *  sentence around it (#585 review). Numbers stay numbers. */
const isolated = (params: Record<string, unknown>) =>
  Object.fromEntries(Object.entries(params).map(([key, value]) => [key, typeof value === "string" ? isolate(value) : value]));

export function titleOf(t: TFunction, item: Pick<ProactiveItem, "title_key" | "params">): string {
  return t(`proactive.${item.title_key}`, { ...isolated(item.params), ...countOf(item.params) }) as string;
}

/** The catalog key a line is translated under. `sched.state` has two wordings (still failing /
 * already paused); the backend sends which one as a flag, not as two keys. */
export function evidencePath(evidence: Pick<ProactiveEvidence, "key" | "params">): string {
  if (evidence.key === "sched.state") return evidence.params.paused ? "sched.state.paused" : "sched.state.failing";
  return evidence.key;
}

export function evidenceLines(t: TFunction, language: string, evidence: ProactiveEvidence[]): EvidenceLine[] {
  return evidence.map((line) => {
    const params: Record<string, unknown> = { ...isolated(line.params), ...countOf(line.params) };
    if (typeof line.params.at === "string") params.at = formatUiDateTime(line.params.at, language);
    return { key: line.key, text: t(`proactive.evidence.${evidencePath(line)}`, params) as string, ...(line.quote ? { quote: line.quote } : {}) };
  });
}

/** `items` or `settings`, then the server's error code; an unknown code or a dead connection
 * gets an honest generic line rather than "HTTP 500". */
export function proactiveErrorText(t: TFunction, scope: "item" | "settings", error: unknown): string {
  const scoped = scope === "item" ? "proactive.item.errors" : "proactive.settings.errors";
  const code = error instanceof ApiError ? error.message : "network";
  const key = `${scoped}.${code}`;
  return (t(key, { defaultValue: "" }) as string) || (t(`${scoped}.generic`) as string);
}

/** One sentence and the outside text that goes with it. Consecutive lines that say the same
 * thing ("Added", "Added") are shown once with all their quotes, so a card lists what changed
 * instead of repeating the label before every line. */
export interface EvidenceGroup { key: string; text: string; quotes: string[] }

export function groupEvidence(lines: EvidenceLine[]): EvidenceGroup[] {
  const groups: EvidenceGroup[] = [];
  for (const line of lines) {
    const last = groups[groups.length - 1];
    if (last && last.text === line.text) { if (line.quote) last.quotes.push(line.quote); continue; }
    groups.push({ key: line.key, text: line.text, quotes: line.quote ? [line.quote] : [] });
  }
  return groups;
}
