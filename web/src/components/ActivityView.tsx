import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, Globe, MessageSquare, Smartphone, Timer, X } from "lucide-react";
import { api } from "../api/client";
import type { RunListItem } from "../api/client.types";
import type { WaitingView } from "../hooks/useWaiting";
import { formatUiDateTime } from "../lib/localeFormatting";
import { fmtMs } from "../lib/usageFormat";
import { useActivityStore } from "../stores/activityStore";
import UsageCard from "./UsageCard";
import HandsTraceCard from "./HandsTraceCard";
import JudgmentsCard from "./JudgmentsCard";
import ScrollBox from "./activity/ScrollBox";
import RunDrawer from "./activity/RunDrawer";
import RunInspector from "./activity/RunInspector";
import { COLOUR, outcomeOf } from "./activity/RunsLane";

/** One page of 最近的工作; the next loads when the box reaches its end. */
export const RUNS_PAGE = 20;

export const ORIGIN_ICON = {
  chat: MessageSquare, job: Timer, scheduled: CalendarClock, phone: Smartphone, browser: Globe,
} as const;

/**
 * Activity (0.1.48), called Progress since v0.1.64 (INB7-a): what Arslan did, what it cost, and what waits on you.
 *
 * Order (0.1.50, user ruling): usage, scheduled tasks, Hands, recent work, judgments. Since INB7-c1 (board F): usage and the
 * axis, then 「最近的工作」 with the inspector beside it (one pick: a row or a bar), then Hands and judgments until INB7-c4 folds them.
 * 0.1.58 §7: each list sits in its own box that scrolls inside and loads 20 at a time;
 * a run opens in a drawer over the page, so the list keeps its place and the opened row
 * stays highlighted; clicking a chart slice or a model narrows 最近的工作; and all of it
 * (range, filter, open run, scroll) survives leaving the page and coming back.
 */
export default function ActivityView({ waiting }: { waiting: WaitingView }) {
  const { t, i18n } = useTranslation();
  const filter = useActivityStore((s) => s.filter);
  const setFilter = useActivityStore((s) => s.setFilter);
  const openRunId = useActivityStore((s) => s.openRunId);
  const setOpenRun = useActivityStore((s) => s.setOpenRun);
  const pickedRunId = useActivityStore((s) => s.pickedRunId);
  const setPickedRun = useActivityStore((s) => s.setPickedRun);
  const pageTop = useActivityStore((s) => s.scroll.page ?? 0);
  const saveScroll = useActivityStore((s) => s.saveScroll);
  const pageRef = useRef<HTMLDivElement>(null);
  const [runs, setRuns] = useState<RunListItem[] | null>(null);
  const [more, setMore] = useState(true);
  const [failed, setFailed] = useState(false);
  const loading = useRef(false);

  useLayoutEffect(() => {
    if (pageRef.current && pageTop) pageRef.current.scrollTop = pageTop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    loading.current = true;
    api.listRuns({ limit: RUNS_PAGE, since: filter.since, until: filter.until, model: filter.model })
      .then((r) => { if (!cancelled) { setRuns(r); setMore(r.length === RUNS_PAGE); setFailed(false); } })
      .catch(() => { if (!cancelled) setFailed(true); })
      .finally(() => { loading.current = false; });
    return () => { cancelled = true; };
  }, [filter.since, filter.until, filter.model]);

  const loadMore = useCallback(() => {
    if (!more || loading.current || !runs?.length) return;
    loading.current = true;
    api.listRuns({ limit: RUNS_PAGE, beforeId: runs[runs.length - 1].id, since: filter.since, until: filter.until, model: filter.model })
      .then((r) => { setRuns((prev) => [...(prev ?? []), ...r]); setMore(r.length === RUNS_PAGE); })
      .catch(() => setMore(false))
      .finally(() => { loading.current = false; });
  }, [more, runs, filter.since, filter.until, filter.model]);

  const showRun = useActivityStore((s) => s.showRun);
  const step = useCallback((delta: -1 | 1) => {
    if (!runs?.length || openRunId == null) return;
    const i = runs.findIndex((r) => r.id === openRunId);
    const next = runs[Math.min(runs.length - 1, Math.max(0, (i < 0 ? 0 : i) + delta))];
    if (next) {
      showRun(next.id, next);                      // the pick follows the drawer (⓪Plan's review of PR 624, B)
      document.querySelector(`[data-testid="activity-run-${next.id}"]`)?.scrollIntoView?.({ block: "nearest" });
    }
  }, [runs, openRunId, showRun]);

  const statusLabel = (s: string) =>
    s === "failed" ? t("activityPage.failed")
      : s === "recording" ? t("activityPage.running")
      : s === "cancelled" ? t("activityPage.cancelled")
      : t("activityPage.done");

  const filtered = filter.since != null || !!filter.model;
  const spanLabel = filter.since != null && filter.until != null
    ? `${formatUiDateTime(new Date(filter.since * 1000).toISOString(), i18n.language)} – ${formatUiDateTime(new Date(filter.until * 1000).toISOString(), i18n.language)}`
    : "";

  return (
    <div ref={pageRef} className="flex-1 h-full overflow-auto p-6 space-y-8" data-testid="activity-view"
      onScroll={(e) => saveScroll("page", e.currentTarget.scrollTop)}>
      <UsageCard waiting={waiting} />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
      <section className="min-w-0">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-medium text-foreground">{t("activityPage.recent")}</h2>
          {runs && runs.length > 0 && (
            <span className="font-mono text-[11px] text-subtle-foreground" data-testid="activity-runs-count">
              {more ? t("activityPage.shownMore", { n: runs.length }) : runs.length}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 mb-3">{t("activityPage.recentHint")}</p>
        {filtered && (
          <div className="mb-2 flex flex-wrap items-center gap-2" data-testid="activity-filter">
            {spanLabel && <FilterChip label={t("activityPage.onlySpan", { span: spanLabel })}
              onClear={() => setFilter({ model: filter.model })} />}
            {filter.model && <FilterChip label={t("activityPage.onlyModel", { model: filter.model })}
              onClear={() => setFilter({ since: filter.since, until: filter.until })} />}
          </div>
        )}
        {failed ? (
          <p className="text-xs text-destructive">{t("activityPage.loadFailed")}</p>
        ) : runs == null ? null : runs.length === 0 ? (
          <p className="text-xs text-subtle-foreground" data-testid="activity-empty">
            {t(filtered ? "activityPage.noneInFilter" : "activityPage.none")}</p>
        ) : (
          <ScrollBox scrollKey="runs" onEnd={loadMore} testId="activity-runs-box">
            <ul className="divide-y divide-border">
              {runs.map((r) => {
                const origin = r.origin ?? "chat";
                const Icon = ORIGIN_ICON[origin] ?? MessageSquare;
                const picked = r.id === pickedRunId;
                return (
                  <li key={r.id}>
                    {/* INB7-c1: a row picks the run for the inspector (and the axis); picking it again lets it go. */}
                    <button
                      type="button"
                      data-testid={`activity-run-${r.id}`}
                      aria-current={picked ? "true" : undefined}
                      onClick={() => setPickedRun(picked ? null : r.id, r)}
                      className={`w-full flex items-center gap-3 px-3 py-2 text-left ${picked ? "bg-primary/10" : "hover:bg-surface/70"}`}
                    >
                      <Icon size={14} aria-label={t(`activityPage.origin_${origin}`)} data-origin={origin}
                        className="shrink-0 text-muted-foreground" />
                      <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${COLOUR[outcomeOf(r)]}`} />
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
                );
              })}
            </ul>
          </ScrollBox>
        )}
      </section>
      <RunInspector runs={runs ?? []} />
      </div>
      <HandsTraceCard />
      <JudgmentsCard />
      {openRunId != null && <RunDrawer runId={openRunId} onClose={() => setOpenRun(null)} onStep={step} />}
    </div>
  );
}

function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5 text-[11.5px] text-primary">
      {label}
      <button type="button" onClick={onClear} aria-label={t("activityPage.clearFilter")} className="rounded-full p-0.5 hover:bg-primary/15">
        <X size={11} aria-hidden />
      </button>
    </span>
  );
}
