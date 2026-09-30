import type { TFunction } from "i18next";
import { ApiError } from "../api/client";
import type { ProactiveEvidence, ProactiveItem } from "../api/proactive";
import { formatUiDateTime } from "./localeFormatting";

/** One line of "why": `text` is the sentence; `quote` is text that came from outside (a page, a
 * file name, an earlier request) and is only ever shown, in quotation marks. */
export interface EvidenceLine { key: string; text: string; quote?: string }

const countOf = (params: Record<string, unknown>) => (typeof params.count === "number" ? { count: params.count } : {});

export function titleOf(t: TFunction, item: Pick<ProactiveItem, "title_key" | "params">): string {
  return t(`proactive.${item.title_key}`, { ...item.params, ...countOf(item.params) }) as string;
}

/** The catalog key a line is translated under. `sched.state` has two wordings (still failing /
 * already paused); the backend sends which one as a flag, not as two keys. */
export function evidencePath(evidence: Pick<ProactiveEvidence, "key" | "params">): string {
  if (evidence.key === "sched.state") return evidence.params.paused ? "sched.state.paused" : "sched.state.failing";
  return evidence.key;
}

export function evidenceLines(t: TFunction, language: string, evidence: ProactiveEvidence[]): EvidenceLine[] {
  return evidence.map((line) => {
    const params: Record<string, unknown> = { ...line.params, ...countOf(line.params) };
    if (typeof params.at === "string") params.at = formatUiDateTime(params.at, language);
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
