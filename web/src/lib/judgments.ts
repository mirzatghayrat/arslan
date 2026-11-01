import { Bookmark, CircleCheckBig, Flag, type LucideIcon } from "lucide-react";

/** One row of the judgment ledger (server/services/judgment.py). Since INB7-c4c a run's judgments show in its 「诊断」, not in a
 *  card of their own. */
export interface JudgmentRow {
  id: number;
  point: string;
  mode: string;
  verdict: boolean | null;
  probability: number | null;
  latency_ms: number | null;
  outcome: string | null;
  created_at: string;
  conversation_id?: string | null;
}

export const POINT_KEY: Record<string, string> = {
  "memory.worth": "activityPage.pointWorth",
  "memory.merge": "activityPage.pointMerge",
  "memory.same": "activityPage.pointSame",
  "memory.applied": "activityPage.pointApplied",
  "memory.conflict": "activityPage.pointConflict",
  "job.accomplished": "activityPage.pointAccomplished",
  "project.progress": "activityPage.pointProgress",
  "project.progress.item": "activityPage.pointProgressItem",
};

/** 0.1.58 §7: one small icon per family of question. */
export function judgmentIcon(point: string): LucideIcon {
  if (point.startsWith("memory.")) return Bookmark;
  if (point.startsWith("project.")) return Flag;
  return CircleCheckBig;
}

/** What the judge said, in words: yes or no with how sure, or no answer. */
export function judgmentVerdict(t: (key: string, options?: Record<string, unknown>) => string, r: JudgmentRow): string {
  return r.verdict == null || r.probability == null
    ? t("activityPage.judgeNoAnswer")
    : t(r.verdict ? "activityPage.judgeYes" : "activityPage.judgeNo", { p: Math.round((r.verdict ? r.probability : 1 - r.probability) * 100) });
}
