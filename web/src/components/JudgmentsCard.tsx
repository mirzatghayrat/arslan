import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { request } from "../api/client";
import { judgmentIcon, judgmentVerdict, POINT_KEY, type JudgmentRow } from "../lib/judgments";
import { formatUiDateTime } from "../lib/localeFormatting";
import ScrollBox from "./activity/ScrollBox";

const PAGE = 20;

/**
 * Activity › Judgments (0.1.52 S2): what Arslan's fast model was asked and what it said, every one of them. Since INB7-c4c a run's
 * own judgments show in its 「诊断」; this full ledger is kept under "Show all" at the foot of Progress until the user decides
 * whether it stays (⓪Plan, PR 636).
 */
export default function JudgmentsCard() {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState<JudgmentRow[] | null>(null);
  const [more, setMore] = useState(false);
  const loading = useRef(false);

  useEffect(() => {
    let cancelled = false;
    request<{ items: JudgmentRow[] }>(`/judgments?limit=${PAGE}`)
      .then((body) => { if (!cancelled) { setRows(body.items); setMore(body.items.length === PAGE); } })
      .catch(() => { if (!cancelled) setRows([]); });
    return () => { cancelled = true; };
  }, []);

  const loadMore = useCallback(() => {
    if (!more || loading.current || !rows?.length) return;
    loading.current = true;
    request<{ items: JudgmentRow[] }>(`/judgments?limit=${PAGE}&before_id=${rows[rows.length - 1].id}`)
      .then((body) => { setRows((prev) => [...(prev ?? []), ...body.items]); setMore(body.items.length === PAGE); })
      .catch(() => setMore(false))
      .finally(() => { loading.current = false; });
  }, [more, rows]);

  if (!rows || rows.length === 0) return null;
  const verdict = (r: JudgmentRow) => judgmentVerdict(t, r);
  return (
    <section data-testid="judgments-card">
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-medium text-foreground">{t("activityPage.judgments")}</h2>
        <span className="font-mono text-[11px] text-subtle-foreground">{more ? t("activityPage.shownMore", { n: rows.length }) : rows.length}</span>
      </div>
      <p className="text-xs text-muted-foreground mt-0.5 mb-3">{t("activityPage.judgmentsHint")}</p>
      <ScrollBox scrollKey="judgments" onEnd={loadMore} testId="judgments-box">
        <ul className="divide-y divide-border">
          {rows.map((r) => {
            const Icon = judgmentIcon(r.point);
            return (
              <li key={r.id} data-testid={`judgment-${r.id}`} className="flex items-center gap-3 px-3 py-2 text-[12px]">
                <Icon size={14} aria-hidden data-point-icon={r.point} className="shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate text-foreground">{t(POINT_KEY[r.point] ?? r.point)}</span>
                {r.mode === "shadow" && <span className="shrink-0 rounded px-1.5 text-[10px] uppercase tracking-wide text-subtle-foreground border border-border">{t("activityPage.judgeShadow")}</span>}
                <span className="shrink-0 rounded-full bg-fill px-2 py-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">{verdict(r)}</span>
                <span className="shrink-0 w-24 text-right text-muted-foreground">
                  {r.outcome === "approved" ? t("activityPage.youApproved") : r.outcome === "declined" ? t("activityPage.youDeclined") : ""}
                </span>
                <span className="shrink-0 w-32 text-right font-mono text-[11px] text-subtle-foreground">{formatUiDateTime(r.created_at, i18n.language)}</span>
              </li>
            );
          })}
        </ul>
      </ScrollBox>
    </section>
  );
}
