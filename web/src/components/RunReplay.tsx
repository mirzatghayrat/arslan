import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { toUiRun } from "../api/adapters";
import type { UiRun } from "../types";

const STATUS_ICON: Record<string, string> = { pass: "✓", warn: "⚠", fail: "✗" };
const BADGE_LABEL: Record<string, string> = { good: "好", ok: "一般", bad: "差" };

interface Props {
  runId: number;
  onClose: () => void;
  /** Poll interval while a run is not yet scored (ms). */
  pollMs?: number;
}

export default function RunReplay({ runId, onClose, pollMs = 1500 }: Props) {
  const [run, setRun] = useState<UiRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const ui = toUiRun(await api.getRun(runId));
        if (cancelled) return;
        setRun(ui);
        if (!ui.scored && ui.status !== "score_failed") {
          timer.current = setTimeout(load, pollMs);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    }
    load();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [runId, pollMs]);

  if (error) return <div className="run-replay run-replay--error" role="alert">{error}</div>;
  if (!run) return <div className="run-replay run-replay--loading">…</div>;

  const maxMs = run.steps.reduce((m, s) => Math.max(m, s.durationMs ?? 0), 0) || 1;

  return (
    <div className="run-replay" data-testid="run-replay">
      <header className="run-replay__head">
        <span className="run-replay__icon" aria-hidden>⟲</span>
        <span className="run-replay__title">编排回放</span>
        <span className="run-replay__sub">run #{run.id} · {run.spawnName ?? ""}</span>
        <button className="run-replay__close" onClick={onClose} aria-label="close">✕</button>
      </header>

      <p className="run-replay__usermsg">{run.userMessage}</p>

      <div className="run-replay__kpis">
        <div className="kpi">
          <div className="kpi__label">总耗时</div>
          <div className="kpi__value">{run.totalMs != null ? `${(run.totalMs / 1000).toFixed(1)}s` : "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">tokens</div>
          <div className="kpi__value">{run.taskTokens}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">评分</div>
          <div className="kpi__value">
            {run.scored && run.overallScore != null ? `${run.overallScore}/10` : "—"}
          </div>
        </div>
      </div>

      <section className="run-replay__trace">
        <h4>它做了什么</h4>
        <ul className="trace">
          {run.steps.map((s) => (
            <li key={s.seq} className={`trace__row${s.isSlowest ? " trace__row--slow" : ""}`}>
              <span className={`trace__label trace__label--${s.kind}`}>{s.label}</span>
              <span className="trace__track">
                <span className="trace__bar" style={{ width: `${((s.durationMs ?? 0) / maxMs) * 100}%` }} />
              </span>
              <span className="trace__ms">{s.durationMs != null ? `${s.durationMs}ms` : ""}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="run-replay__eval">
        <h4>做得怎么样</h4>
        {run.scored ? (
          <>
            <div className={`verdict verdict--${run.overallBadge ?? "ok"}`}>
              {BADGE_LABEL[run.overallBadge ?? "ok"]} · {run.overallScore}/10
            </div>
            <ul className="dims">
              {run.dimensions.map((d) => (
                <li key={d.dimension} className={`dim dim--${d.status}`}>
                  <span className="dim__icon" aria-hidden>{STATUS_ICON[d.status]}</span>
                  <span className="dim__label">{d.label}: </span>
                  <span className="dim__comment">{d.comment}</span>
                  <span className="dim__bar"><span style={{ width: `${(d.score / 10) * 100}%` }} /></span>
                  <span className="dim__score">{d.score}</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="run-replay__pending">评分中…</p>
        )}
      </section>
    </div>
  );
}
