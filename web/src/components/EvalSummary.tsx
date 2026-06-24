import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunListItem } from "../api/client.types";
import RunReplay from "./RunReplay";

interface Props {
  onClose: () => void;
  spawnId?: number;
}

export default function EvalSummary({ onClose, spawnId }: Props) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [viewRunId, setViewRunId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getRuns(spawnId)
      .then((r) => { if (!cancelled) setRuns(r); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [spawnId]);

  if (viewRunId != null) {
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
    <div className="eval-summary" data-testid="eval-summary">
      <header className="eval-summary__head">
        <span className="eval-summary__title">评估摘要</span>
        <button className="eval-summary__close" onClick={onClose} aria-label="close">✕</button>
      </header>

      {error && <div className="eval-summary__error" role="alert">{error}</div>}

      <div className="eval-summary__kpis">
        <div className="kpi"><div className="kpi__label">已评分</div><div className="kpi__value">{scored.length}</div></div>
        <div className="kpi"><div className="kpi__label">平均分</div><div className="kpi__value">{avg ?? "暂无评分"}</div></div>
        <div className="kpi"><div className="kpi__label">达标率</div><div className="kpi__value">{passRate != null ? `${passRate}%` : "—"}</div></div>
      </div>

      {runs.length === 0 ? (
        <p className="eval-summary__empty">还没有运行记录</p>
      ) : (
        <ul className="eval-list">
          {runs.map((r) => (
            <li key={r.id} className="eval-list__row" onClick={() => setViewRunId(r.id)}>
              <span className="eval-list__spawn">{r.spawn_name ?? "—"}</span>
              <span className={`eval-list__badge eval-list__badge--${r.overall_badge ?? "none"}`}>
                {r.overall_badge ?? ""}
              </span>
              <span className="eval-list__score">
                {r.status === "scored" && r.overall_score != null ? `${r.overall_score}/10` : "评分中"}
              </span>
              <span className="eval-list__ms">{r.total_ms != null ? `${(r.total_ms / 1000).toFixed(1)}s` : ""}</span>
              <span className="eval-list__msg">{r.user_message.slice(0, 40)}{r.user_message.length > 40 ? "…" : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
