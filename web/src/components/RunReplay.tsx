import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { toUiRun } from "../api/adapters";
import type { UiRun } from "../types";
import RunCompareChart from "./RunCompareChart";

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
  const [openSteps, setOpenSteps] = useState<Set<number>>(new Set());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function toggleStep(seq: number) {
    setOpenSteps((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  }

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
          {run.steps.map((s) => {
            const isOpen = openSteps.has(s.seq);
            const detail = s.detail;
            return (
              <li
                key={s.seq}
                className={`trace__row${s.isSlowest ? " trace__row--slow" : ""}${isOpen ? " trace__row--open" : ""}`}
                onClick={() => toggleStep(s.seq)}
                role="button"
                tabIndex={0}
              >
                <div className="trace__summary">
                  <span className={`trace__label trace__label--${s.kind}`}>{s.label}</span>
                  <span className="trace__track">
                    <span className="trace__bar" style={{ width: `${((s.durationMs ?? 0) / maxMs) * 100}%` }} />
                  </span>
                  <span className="trace__ms">{s.durationMs != null ? `${s.durationMs}ms` : ""}</span>
                </div>
                {isOpen && (
                  <div className="trace__detail">
                    {s.kind === "tool_call" && (
                      <>
                        {s.ok != null && (
                          <div className="trace__detail-row">
                            <span className="trace__detail-key">状态</span>
                            <span className={`trace__detail-val trace__ok--${s.ok ? "yes" : "no"}`}>
                              {s.ok ? "✓" : "✗"}
                            </span>
                          </div>
                        )}
                        {detail?.args_summary != null && (
                          <div className="trace__detail-row">
                            <span className="trace__detail-key">查询</span>
                            <span className="trace__detail-val trace__detail-val--mono">{String(detail.args_summary)}</span>
                          </div>
                        )}
                        {detail?.summary != null && (
                          <div className="trace__detail-row">
                            <span className="trace__detail-key">结果</span>
                            <span className="trace__detail-val">{String(detail.summary)}</span>
                          </div>
                        )}
                      </>
                    )}
                    {s.kind === "dispatch" && detail?.output_preview != null && (
                      <div className="trace__detail-row">
                        <span className="trace__detail-key">输出</span>
                        <span className="trace__detail-val trace__detail-val--mono">{String(detail.output_preview)}</span>
                      </div>
                    )}
                    {s.kind === "escalation" && (
                      <>
                        {detail?.how != null && (
                          <div className="trace__detail-row">
                            <span className="trace__detail-key">如何</span>
                            <span className="trace__detail-val">{String(detail.how)}</span>
                          </div>
                        )}
                        {detail?.why != null && (
                          <div className="trace__detail-row">
                            <span className="trace__detail-key">为何</span>
                            <span className="trace__detail-val">{String(detail.why)}</span>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </li>
            );
          })}
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

      {/* This run against the fleet averages (self-hides when <2 scored runs
          or the summary fetch fails). Only meaningful once the run is scored. */}
      {run.scored && (
        <RunCompareChart dimensions={run.dimensions} overallScore={run.overallScore} />
      )}
    </div>
  );
}
