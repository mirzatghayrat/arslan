import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { RunListItem } from "../api/client.types";
import RunReplay from "./RunReplay";
import EvalCharts from "./EvalCharts";

interface Props {
  onClose: () => void;
  spawnId?: number;
  /**
   * When set, the view defaults to THIS conversation's runs only, with a
   * 本会话/全部会话 toggle to widen to everything. Omitted → global list,
   * exactly the pre-existing behaviour (no toggle shown).
   */
  conversationId?: string;
  /**
   * When `inline` is set, EvalSummary renders bare (no internal full-screen
   * RunReplay swap, no close button) so it can be embedded in the EvalDock
   * slide-up region. Clicking a run is reported via `onSelectRun` instead of
   * opening RunReplay internally. Omitting `inline` keeps the original
   * overlay behaviour intact for any other caller.
   */
  inline?: boolean;
  /** Notified with a run id when a run row is clicked (inline mode). */
  onSelectRun?: (runId: number) => void;
}

export default function EvalSummary({ onClose, spawnId, conversationId, inline = false, onSelectRun }: Props) {
  const { t } = useTranslation();
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [viewRunId, setViewRunId] = useState<number | null>(null);
  const [clearingAll, setClearingAll] = useState(false);
  // Scope toggle only exists when a conversationId is provided; defaults to
  // the current conversation (the reason the user opened the view from a chat).
  const [scope, setScope] = useState<"conversation" | "all">("conversation");
  const conversationScoped = conversationId != null && scope === "conversation";

  function reloadRuns() {
    return api.getRuns(spawnId, 50, conversationScoped ? conversationId : undefined)
      .then((r) => setRuns(r))
      .catch((e) => setError(String(e)));
  }

  useEffect(() => {
    let cancelled = false;
    api.getRuns(spawnId, 50, conversationScoped ? conversationId : undefined)
      .then((r) => { if (!cancelled) setRuns(r); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [spawnId, conversationId, conversationScoped]);

  const handleRowClick = (runId: number) => {
    if (inline) onSelectRun?.(runId);
    else setViewRunId(runId);
  };

  async function handleClearAll() {
    if (!window.confirm(t("diag.clear_all_confirm"))) {
      return;
    }
    setClearingAll(true);
    try {
      await api.redactAllRuns();
      await reloadRuns();
    } finally {
      setClearingAll(false);
    }
  }

  if (!inline && viewRunId != null) {
    return <RunReplay runId={viewRunId} onClose={() => setViewRunId(null)} />;
  }

  const scored = runs.filter((r) => r.status === "scored" && r.overall_score != null);
  const avg = scored.length
    ? (scored.reduce((s, r) => s + (r.overall_score ?? 0), 0) / scored.length).toFixed(1)
    : null;
  const passRate = scored.length
    ? Math.round((scored.filter((r) => (r.overall_score ?? 0) >= 7).length / scored.length) * 100)
    : null;

  return (
    <div className={`eval-summary${inline ? " eval-summary--inline" : ""}`} data-testid="eval-summary">
      {!inline && (
        <header className="eval-summary__head">
          <span className="eval-summary__title">{t("diag.eval_summary")}</span>
          <button className="eval-summary__close" onClick={onClose} aria-label="close">✕</button>
        </header>
      )}

      {error && <div className="eval-summary__error" role="alert">{error}</div>}

      {/* Scope toggle — only when opened from a conversation. Renders in both
          overlay and inline (EvalDock) modes, so it lives above the KPIs
          rather than inside the overlay-only header. */}
      {conversationId != null && (
        <div className="eval-summary__scope" role="tablist" aria-label="scope">
          <button
            type="button"
            role="tab"
            aria-selected={scope === "conversation"}
            className={`eval-summary__scope-btn${scope === "conversation" ? " eval-summary__scope-btn--active" : ""}`}
            onClick={() => setScope("conversation")}
          >
            {t("eval.scope_conversation")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={scope === "all"}
            className={`eval-summary__scope-btn${scope === "all" ? " eval-summary__scope-btn--active" : ""}`}
            onClick={() => setScope("all")}
          >
            {t("eval.scope_all")}
          </button>
        </div>
      )}

      <div className="eval-summary__kpis">
        <div className="kpi"><div className="kpi__label">{t("diag.scored")}</div><div className="kpi__value">{scored.length}</div></div>
        <div className="kpi"><div className="kpi__label">{t("diag.avg_score")}</div><div className="kpi__value">{avg ?? t("diag.no_scores")}</div></div>
        <div className="kpi"><div className="kpi__label">{t("diag.pass_rate")}</div><div className="kpi__value">{passRate != null ? `${passRate}%` : "—"}</div></div>
      </div>

      {/* Fleet-wide charts only in the global view — under a per-spawn OR
          per-conversation filter the global aggregates would mislead.
          Self-hides when <2 scored. */}
      {spawnId == null && !conversationScoped && <EvalCharts />}

      {runs.length === 0 ? (
        <p className="eval-summary__empty">{t("diag.no_runs")}</p>
      ) : (
        <ul className="eval-list">
          {runs.map((r) => (
            <li key={r.id} className="eval-list__row" onClick={() => handleRowClick(r.id)}>
              <span className="eval-list__spawn">{r.spawn_name ?? "—"}</span>
              <span className={`eval-list__badge eval-list__badge--${r.overall_badge ?? "none"}`}>
                {r.overall_badge ?? ""}
              </span>
              <span className="eval-list__score">
                {r.status === "scored" && r.overall_score != null ? `${r.overall_score}/10` : t("replay.scoring")}
              </span>
              <span className="eval-list__ms">{r.total_ms != null ? `${(r.total_ms / 1000).toFixed(1)}s` : ""}</span>
              <span className="eval-list__msg">{r.user_message.slice(0, 40)}{r.user_message.length > 40 ? "…" : ""}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="eval-summary__footer">
        <button
          type="button"
          className="eval-summary__clear-all-btn"
          onClick={handleClearAll}
          disabled={clearingAll}
        >
          {clearingAll ? t("replay.clearing") : t("diag.clear_all_btn")}
        </button>
      </div>
    </div>
  );
}
