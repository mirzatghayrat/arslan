import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { RunListItem } from "../api/client.types";
import { formatUiDateTime } from "../lib/localeFormatting";
import { fmtMs } from "../lib/usageFormat";
import RunReplay from "./RunReplay";
import UsageCard from "./UsageCard";
import ScheduledTasksCard from "./ScheduledTasksCard";
import HandsTraceCard from "./HandsTraceCard";
import JudgmentsCard from "./JudgmentsCard";

/**
 * Activity (0.1.48): what Arslan did, and what it cost.
 *
 * Replaces Diagnostics. That page was built around experts — a catalog of
 * spawns, per-spawn scores, an evolution inbox — and with experts gone the
 * only parts still describing anything real were usage and scheduled tasks.
 * Order (0.1.50, user ruling): usage first — the at-a-glance picture of what the
 * work did and cost — then scheduled tasks, then recent work. Every answer and
 * background job is a recorded run; opening one shows its step-by-step trace
 * (the same RunReplay the chat links to).
 */
export default function ActivityView() {
  const { t, i18n } = useTranslation();
  const [runs, setRuns] = useState<RunListItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    if (open != null) return;
    let cancelled = false;
    api.getRuns(undefined, 30)
      .then((r) => { if (!cancelled) { setRuns(r); setFailed(false); } })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [open]);

  if (open != null) {
    return (
      <div className="flex-1 h-full overflow-auto p-6">
        <div data-testid="activity-breadcrumb" className="text-[11px] font-mono text-muted-foreground mb-3 flex items-center gap-1.5">
          <button type="button" className="hover:text-foreground" onClick={() => setOpen(null)}>{t("activityPage.back")}</button>
          <span>/</span>
          <span className="text-foreground">{t("activityPage.run", { id: open })}</span>
        </div>
        <RunReplay runId={open} onClose={() => setOpen(null)} />
      </div>
    );
  }

  const statusLabel = (s: string) =>
    s === "failed" ? t("activityPage.failed")
      : s === "recording" ? t("activityPage.running")
      : s === "cancelled" ? t("activityPage.cancelled")
      : t("activityPage.done");

  const dot = (s: string) => s === "failed" ? "bg-danger" : s === "recording" ? "bg-primary animate-pulse"
    : s === "cancelled" || s === "interrupted" ? "bg-subtle-foreground" : "bg-success";

  return (
    <div className="flex-1 h-full overflow-auto p-6 space-y-8" data-testid="activity-view">
      <UsageCard />
      <ScheduledTasksCard onOpenRun={(runId) => setOpen(runId)} />
      <HandsTraceCard />
      <section>
        <h2 className="text-sm font-medium text-foreground">{t("activityPage.recent")}</h2>
        <p className="text-xs text-muted-foreground mt-0.5 mb-3">{t("activityPage.recentHint")}</p>
        {failed ? (
          <p className="text-xs text-destructive">{t("activityPage.loadFailed")}</p>
        ) : runs == null ? null : runs.length === 0 ? (
          <p className="text-xs text-subtle-foreground" data-testid="activity-empty">{t("activityPage.none")}</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border bg-surface/40">
            {runs.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  data-testid={`activity-run-${r.id}`}
                  onClick={() => setOpen(r.id)}
                  className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-surface/70"
                >
                  <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot(r.status)}`} />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-foreground">{r.user_message || "—"}</span>
                  {r.total_ms != null && r.status !== "recording" && (
                    <span className="shrink-0 font-mono text-[11px] tabular-nums text-subtle-foreground"
                      title={t("activityPage.duration", { v: fmtMs(r.total_ms) })}>{fmtMs(r.total_ms)}</span>
                  )}
                  <span className={`shrink-0 w-16 text-right text-[11px] ${r.status === "failed" ? "text-destructive" : "text-muted-foreground"}`}>
                    {statusLabel(r.status)}
                  </span>
                  <span className="shrink-0 w-32 text-right text-[11px] text-subtle-foreground font-mono">
                    {r.created_at ? formatUiDateTime(r.created_at, i18n.language) : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <JudgmentsCard />
    </div>
  );
}
