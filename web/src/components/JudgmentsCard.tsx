import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { request } from "../api/client";
import { formatUiDateTime } from "../lib/localeFormatting";

/** One row of the judgment ledger (server/services/judgment.py). */
export interface JudgmentRow {
  id: number;
  point: string;
  mode: string;
  verdict: boolean | null;
  probability: number | null;
  latency_ms: number | null;
  outcome: string | null;
  created_at: string;
}

const POINT_KEY: Record<string, string> = {
  "tool.approval": "activityPage.pointApproval",
  "memory.worth": "activityPage.pointWorth",
  "memory.merge": "activityPage.pointMerge",
  "memory.applied": "activityPage.pointApplied",
};

/**
 * Activity › Judgments (0.1.52 S2): what Arslan's fast model was asked, what it said,
 * and — for shadow decisions such as "ask before this command?" — what you actually
 * chose. Hidden until there is something to show.
 */
export default function JudgmentsCard() {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState<JudgmentRow[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    request<{ items: JudgmentRow[] }>("/judgments?limit=30")
      .then((body) => { if (!cancelled) setRows(body.items); })
      .catch(() => { if (!cancelled) setRows([]); });
    return () => { cancelled = true; };
  }, []);

  if (!rows || rows.length === 0) return null;
  const verdict = (r: JudgmentRow) => r.verdict == null || r.probability == null
    ? t("activityPage.judgeNoAnswer")
    : t(r.verdict ? "activityPage.judgeYes" : "activityPage.judgeNo",
        { p: Math.round((r.verdict ? r.probability : 1 - r.probability) * 100) });
  return (
    <section data-testid="judgments-card">
      <h2 className="text-sm font-medium text-foreground">{t("activityPage.judgments")}</h2>
      <p className="text-xs text-muted-foreground mt-0.5 mb-3">{t("activityPage.judgmentsHint")}</p>
      <ul className="divide-y divide-border rounded-lg border border-border bg-surface/40">
        {rows.map((r) => (
          <li key={r.id} data-testid={`judgment-${r.id}`} className="flex items-center gap-3 px-3 py-2 text-[12px]">
            <span className="min-w-0 flex-1 truncate text-foreground">{t(POINT_KEY[r.point] ?? r.point)}</span>
            {r.mode === "shadow" && <span className="shrink-0 rounded px-1.5 text-[10px] uppercase tracking-wide text-subtle-foreground border border-border">{t("activityPage.judgeShadow")}</span>}
            <span className="shrink-0 w-20 text-right font-mono tabular-nums text-muted-foreground">{verdict(r)}</span>
            <span className="shrink-0 w-24 text-right text-muted-foreground">
              {r.outcome === "approved" ? t("activityPage.youApproved") : r.outcome === "declined" ? t("activityPage.youDeclined") : ""}
            </span>
            <span className="shrink-0 w-32 text-right font-mono text-[11px] text-subtle-foreground">{formatUiDateTime(r.created_at, i18n.language)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
