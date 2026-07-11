import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { toUiRun, DIMENSION_LABELS } from "../api/adapters";
import type { RunListItem, RunSummary } from "../api/client.types";
import type { UiRun } from "../types";
import RunCompareChart from "./RunCompareChart";
import EChart from "./EChart";
import { triggerDownload } from "./MessageBody";

const STATUS_ICON: Record<string, string> = { pass: "✓", warn: "⚠", fail: "✗" };
const BADGE_LABEL: Record<string, string> = { good: "好", ok: "一般", bad: "差" };

// Fixed axis order for the this-run-vs-fleet radar, matching the backend judge dimensions.
const RADAR_DIMENSIONS = ["routing", "fabrication", "identity", "completion"] as const;

/** Human-readable md export of a run — KPIs, steps, dims/comments, prompt/kb. */
function buildRunMarkdown(run: UiRun): string {
  const lines: string[] = [];
  lines.push(`# Run #${run.id}${run.spawnName ? ` · ${run.spawnName}` : ""}`);
  lines.push("");
  lines.push(`**用户消息**：${run.userMessage}`);
  lines.push("");
  lines.push("## KPI");
  lines.push(`- 总耗时：${run.totalMs != null ? `${(run.totalMs / 1000).toFixed(1)}s` : "—"}`);
  lines.push(`- 模型：${run.model ?? "—"}`);
  lines.push(`- tokens：${run.taskTokens}${run.tokensEstimated ? "（≈）" : ""}`);
  lines.push(`- 评分：${run.scored && run.overallScore != null ? `${run.overallScore}/10` : "—"}`);
  lines.push("");
  lines.push("## 它做了什么");
  for (const s of run.steps) {
    const ms = s.durationMs != null ? `${s.durationMs}ms` : "—";
    lines.push(`- [${s.kind}] ${s.label}（${ms}）`);
  }
  lines.push("");
  lines.push("## 做得怎么样");
  if (run.scored) {
    lines.push(`总评：${BADGE_LABEL[run.overallBadge ?? "ok"]} · ${run.overallScore}/10`);
    for (const d of run.dimensions) {
      lines.push(`- ${d.label}（${Math.round(d.score * 10) / 10}/10）：${d.comment}`);
    }
  } else {
    lines.push("评分中…");
  }
  if (run.injectedKbSources?.length) {
    lines.push("");
    lines.push("## 注入知识来源");
    for (const src of run.injectedKbSources) lines.push(`- ${src}`);
  }
  if (run.systemPrompt != null) {
    lines.push("");
    lines.push("## 系统提示");
    lines.push("```");
    lines.push(run.systemPrompt);
    lines.push("```");
  }
  if (run.injectedKb != null) {
    lines.push("");
    lines.push("## 注入知识");
    lines.push("```");
    lines.push(run.injectedKb);
    lines.push("```");
  }
  return lines.join("\n");
}

/** Terminal run statuses (S3-M1): the run row will never change again, so polling
 * must stop. Without cancelled/interrupted here the panel polls those runs forever
 * — they never reach 'scored' or 'score_failed'. */
const TERMINAL_RUN_STATUSES = new Set([
  "scored", "score_failed", "cancelled", "interrupted", "replayed",
]);

export function isTerminalRunStatus(status: string): boolean {
  return TERMINAL_RUN_STATUSES.has(status);
}

interface Props {
  runId: number;
  onClose: () => void;
  /** Poll interval while a run is not yet in a terminal status (ms). */
  pollMs?: number;
}

export default function RunReplay({ runId, onClose, pollMs = 1500 }: Props) {
  const { t } = useTranslation();
  const [run, setRun] = useState<UiRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openSteps, setOpenSteps] = useState<Set<number>>(new Set());
  const [clearing, setClearing] = useState(false);
  const [dimSummary, setDimSummary] = useState<RunSummary["dimension_averages"] | null>(null);
  const [history, setHistory] = useState<RunListItem[] | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);

  function toggleStep(seq: number) {
    setOpenSteps((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  }

  async function load() {
    try {
      const ui = toUiRun(await api.getRun(runId));
      if (cancelledRef.current) return;
      setRun(ui);
      if (!isTerminalRunStatus(ui.status)) {
        timer.current = setTimeout(load, pollMs);
      }
    } catch (e) {
      if (!cancelledRef.current) setError(String(e));
    }
  }

  useEffect(() => {
    cancelledRef.current = false;
    load();
    return () => {
      cancelledRef.current = true;
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, pollMs]);

  // Dims radar data: fleet dimension averages, best-effort (skip radar on failure).
  useEffect(() => {
    if (!run?.scored) return;
    let cancelled = false;
    api.getRunsSummary()
      .then((s) => { if (!cancelled) setDimSummary(s.dimension_averages); })
      .catch(() => { /* radar is optional */ });
    return () => { cancelled = true; };
  }, [run?.scored]);

  // Spawn history sparkline: recent scored runs for this spawn, best-effort.
  useEffect(() => {
    if (run?.spawnId == null) return;
    let cancelled = false;
    api.getRuns(run.spawnId, 12)
      .then((items) => { if (!cancelled) setHistory(items); })
      .catch(() => { /* sparkline is optional */ });
    return () => { cancelled = true; };
  }, [run?.spawnId]);

  async function handleClearThisRun() {
    if (!window.confirm("确定清除此 run 的调试详情吗？实际系统提示/注入知识/工具完整入参与原始返回将被清除，分数与耗时不受影响。此操作不可撤销。")) {
      return;
    }
    setClearing(true);
    try {
      await api.redactRun(runId);
      await load();
    } finally {
      setClearing(false);
    }
  }

  if (error) return <div className="run-replay run-replay--error" role="alert">{error}</div>;
  if (!run) return <div className="run-replay run-replay--loading">…</div>;

  const tokensNode = run.tokensEstimated
    ? `≈ ${run.taskTokens}`
    : run.tokensIn != null || run.tokensOut != null
      ? `${run.tokensIn ?? "—"} / ${run.tokensOut ?? "—"}`
      : run.taskTokens;

  const hasDebugDetail = run.systemPrompt != null || run.injectedKb != null;

  const maxMs = run.steps.reduce((m, s) => Math.max(m, s.durationMs ?? 0), 0) || 1;

  const routeMs = run.steps.filter((s) => s.kind === "route").reduce((sum, s) => sum + (s.durationMs ?? 0), 0);
  const toolsMs = run.steps.filter((s) => s.kind === "tool_call").reduce((sum, s) => sum + (s.durationMs ?? 0), 0);
  const dispatchMs = run.steps.filter((s) => s.kind === "dispatch").reduce((sum, s) => sum + (s.durationMs ?? 0), 0);
  const composeMs = Math.max(0, dispatchMs - toolsMs);
  const breakdownTotal = routeMs + toolsMs + composeMs || 1;
  const breakdownSegments = [
    { key: "route", label: "路由", ms: routeMs, color: "var(--muted-foreground)" },
    { key: "tools", label: "工具", ms: toolsMs, color: "var(--warning)" },
    { key: "compose", label: "生成", ms: composeMs, color: "var(--primary)" },
  ];

  const outputPreview = run.steps.find((s) => s.kind === "dispatch" && s.detail?.output_preview != null)?.detail
    ?.output_preview as string | undefined;

  // Step waterfall (cumulative-offset gantt): each step's bar starts where the
  // previous one ended, so the row shows the whole run's timeline at a glance.
  const waterfallTotalMs = run.steps.reduce((sum, s) => sum + (s.durationMs ?? 0), 0) || 1;
  let waterfallCursorMs = 0;
  const waterfallRows = run.steps.map((s) => {
    const offsetMs = waterfallCursorMs;
    waterfallCursorMs += s.durationMs ?? 0;
    let color = "var(--muted-foreground)";
    if (s.kind === "route") color = "var(--hue-7)";
    else if (s.kind === "dispatch") color = "var(--hue-6)";
    else if (s.kind === "tool_call") color = s.ok === false ? "var(--danger)" : "var(--hue-5)";
    else if (s.kind === "escalation") color = "var(--warning)";
    const tooltipLabel = s.kind === "tool_call" ? `${s.kind} · ${s.label}` : s.kind;
    return { seq: s.seq, kind: s.kind, label: s.kind, tooltipLabel, offsetMs, durationMs: s.durationMs ?? 0, color };
  });

  // Dims radar: this run's dimension scores vs the fleet averages. Guarded — renders
  // only once both the run is scored, has dimensions, and the summary fetch succeeded.
  const scoreByDim: Record<string, number> = {};
  for (const d of run.dimensions) scoreByDim[d.dimension] = d.score;
  const showRadar = run.scored && run.dimensions.length > 0 && dimSummary != null;
  const radarOption = showRadar
    ? {
        tooltip: {},
        // legend at the BOTTOM so it never collides with the top vertex's axis name
        // (the "路由匹配" overlap); radar recentred up + smaller radius for label clearance.
        legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 10 } },
        radar: {
          indicator: RADAR_DIMENSIONS.map((d) => ({ name: DIMENSION_LABELS[d] ?? d, max: 10, min: 0 })),
          radius: "52%",
          center: ["50%", "44%"],
          axisName: { fontSize: 10 },
        },
        series: [
          {
            type: "radar",
            data: [
              {
                name: "本次",
                value: RADAR_DIMENSIONS.map((d) => scoreByDim[d] ?? 0),
                areaStyle: { opacity: 0.18 },
              },
              {
                name: "舰队平均",
                value: RADAR_DIMENSIONS.map((d) => dimSummary?.[d] ?? 0),
                lineStyle: { type: "dashed" as const },
                areaStyle: { opacity: 0 },
              },
            ],
          },
        ],
      }
    : null;

  // History sparkline: recent scored runs for this run's spawn, current run highlighted.
  const historyScored = (history ?? []).filter((r) => r.overall_score != null);
  const showSparkline = run.spawnId != null && historyScored.length > 0;
  const sparkMax = showSparkline ? Math.max(...historyScored.map((r) => r.overall_score ?? 0), 10) : 1;

  return (
    <div className="run-replay" data-testid="run-replay">
      <header className="run-replay__head">
        <span className="run-replay__icon" aria-hidden>⟲</span>
        <span className="run-replay__title">编排回放</span>
        <span className="run-replay__sub">run #{run.id} · {run.spawnName ?? ""}</span>
        <button className="run-replay__close" onClick={onClose} aria-label="close">✕</button>
      </header>

      <p className="run-replay__usermsg">{run.userMessage}</p>

      {run.errorText != null && (
        <div className="run-replay__error-banner" role="alert">
          {run.errorKind ? `${run.errorKind} · ` : ""}{run.errorText}
        </div>
      )}

      <div className="run-replay__kpis">
        <div className="kpi">
          <div className="kpi__label">总耗时</div>
          <div className="kpi__value">{run.totalMs != null ? `${(run.totalMs / 1000).toFixed(1)}s` : "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">模型</div>
          <div className="kpi__value kpi__value--text">{run.model ?? "—"}</div>
        </div>
        <div className="kpi">
          <div className="kpi__label">tokens</div>
          <div className="kpi__value">{tokensNode}</div>
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

        <div className="time-breakdown" data-testid="time-breakdown">
          <div className="time-breakdown__bar">
            {breakdownSegments.map((seg) =>
              seg.ms > 0 ? (
                <span
                  key={seg.key}
                  className="time-breakdown__seg"
                  style={{ width: `${(seg.ms / breakdownTotal) * 100}%`, background: seg.color }}
                  title={`${seg.label} ${seg.ms}ms`}
                />
              ) : null
            )}
          </div>
          <div className="time-breakdown__legend">
            {breakdownSegments.map((seg) => (
              <span key={seg.key} className="time-breakdown__legend-item">
                <span className="time-breakdown__swatch" style={{ background: seg.color }} />
                {seg.label} {Math.round((seg.ms / breakdownTotal) * 100)}%
              </span>
            ))}
          </div>
        </div>

        {run.steps.length > 0 && (
          <section className="run-replay__waterfall" data-testid="run-waterfall">
            <h4>步骤瀑布</h4>
            {waterfallRows.map((row) => (
              <div className="wf-row" data-testid="wf-row" key={row.seq}>
                <span className="wf-label" title={row.tooltipLabel}>{row.label}</span>
                <span className="wf-track">
                  <span
                    className="wf-bar"
                    data-testid="wf-bar"
                    style={{
                      left: `${(row.offsetMs / waterfallTotalMs) * 100}%`,
                      width: `max(0.6%, ${(row.durationMs / waterfallTotalMs) * 100}%)`,
                      background: row.color,
                    }}
                    title={`${row.durationMs}ms`}
                  />
                </span>
              </div>
            ))}
          </section>
        )}

        <ul className="trace">
          {run.steps.map((s) => {
            const isOpen = openSteps.has(s.seq);
            const detail = s.detail;
            if (s.kind === "tool_call") {
              return (
                <li
                  key={s.seq}
                  className={`trace__row tool-card${s.isSlowest ? " trace__row--slow" : ""}${isOpen ? " trace__row--open" : ""}`}
                  data-testid="tool-card"
                  onClick={() => toggleStep(s.seq)}
                  role="button"
                  tabIndex={0}
                >
                  <div className="tool-card__summary">
                    <span className="tool-card__icon" aria-hidden>🔧</span>
                    <span className="tool-card__label">{s.label}</span>
                    {s.ok != null && (
                      <span className={`tool-card__status trace__ok--${s.ok ? "yes" : "no"}`}>
                        {s.ok ? "✓" : "✗"}
                      </span>
                    )}
                    <span className="trace__ms">{s.durationMs != null ? `${s.durationMs}ms` : ""}</span>
                  </div>
                  {isOpen && (
                    <div className="trace__detail tool-card__body">
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
                      {s.argsFull != null && (
                        <div className="trace__detail-row trace__detail-row--block">
                          <span className="trace__detail-key">完整入参</span>
                          <pre className="trace__detail-val trace__detail-val--mono trace__detail-val--pre">{s.argsFull}</pre>
                        </div>
                      )}
                      {s.resultRaw != null && (
                        <div className="trace__detail-row trace__detail-row--block">
                          <span className="trace__detail-key">原始返回</span>
                          <pre className="trace__detail-val trace__detail-val--mono trace__detail-val--pre">{s.resultRaw}</pre>
                        </div>
                      )}
                      {s.error != null && (
                        <div className="trace__detail-row trace__detail-row--block">
                          <span className="trace__detail-key">工具错误</span>
                          <pre className="trace__detail-val trace__detail-val--mono trace__detail-val--pre trace__detail-val--error">{s.error}</pre>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            }
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

        {outputPreview != null && (
          <div className="output-preview">
            <div className="output-preview__label">产出预览</div>
            <p className="output-preview__text">{outputPreview}</p>
          </div>
        )}

        {/* M4 final review I-1: scheduled runs' deliverables land in a dedicated
            conversation the sidebar can't reach, so the run row carries the full
            text — render it here so the Diagnostics → history → RunReplay chain
            is the complete reading path. Absent for plain live runs. */}
        {run.finalOutput != null && (
          <details className="run-replay__final-output" data-testid="final-output">
            <summary>完整产出</summary>
            <pre className="trace__detail-val trace__detail-val--mono trace__detail-val--pre">{run.finalOutput}</pre>
          </details>
        )}
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
        ) : run.status === "cancelled" || run.status === "interrupted" ? (
          /* S3-M1: cancelled/interrupted runs will never be scored — showing
             "评分中…" forever would be a lie. Same interrupted wording as the
             chat stall/cancel markers (working.stalled = 已中断/Interrupted). */
          <p className="run-replay__pending">⏸ {t("working.stalled")}</p>
        ) : (
          <p className="run-replay__pending">评分中…</p>
        )}
      </section>

      {/* Per-dimension radar: this run vs the fleet average, on the same 4 axes.
          Best-effort — hides silently if the summary fetch fails or there are no dims yet. */}
      {showRadar && radarOption && (
        <section className="run-replay__radar" data-testid="dims-radar">
          <h4>本次 vs 舰队(雷达)</h4>
          <EChart option={radarOption} height={230} />
        </section>
      )}

      {/* Spawn history sparkline: recent scored runs for this spawn, current run highlighted.
          Hides silently when the run has no spawn or there's no history yet. */}
      {showSparkline && (
        <section className="run-replay__history" data-testid="history-spark">
          <h4>该分身近期评分</h4>
          <div className="history-spark__bars">
            {historyScored.map((r) => (
              <span
                key={r.id}
                className={`history-spark__bar${r.id === run.id ? " history-spark__bar--current" : ""}`}
                style={{ height: `${((r.overall_score ?? 0) / sparkMax) * 100}%` }}
                title={`run #${r.id}: ${r.overall_score}/10`}
              />
            ))}
          </div>
        </section>
      )}

      {/* This run against the fleet averages (self-hides when <2 scored runs
          or the summary fetch fails). Only meaningful once the run is scored. */}
      {run.scored && (
        <RunCompareChart dimensions={run.dimensions} overallScore={run.overallScore} />
      )}

      <section className="run-replay__debug">
        {run.injectedKbSources != null && run.injectedKbSources.length > 0 && (
          <div className="kb-chips">
            {run.injectedKbSources.map((src, i) => (
              <span key={`${src}-${i}`} className="kb-chip">{src}</span>
            ))}
          </div>
        )}

        <details className="run-replay__prompt-details">
          <summary>实际系统提示 / 注入的知识</summary>
          {hasDebugDetail ? (
            <>
              {run.systemPrompt != null && (
                <div className="trace__detail-row trace__detail-row--block">
                  <span className="trace__detail-key">系统提示</span>
                  <pre className="trace__detail-val trace__detail-val--mono trace__detail-val--pre">{run.systemPrompt}</pre>
                </div>
              )}
              {run.injectedKb != null && (
                <div className="trace__detail-row trace__detail-row--block">
                  <span className="trace__detail-key">注入知识</span>
                  <pre className="trace__detail-val trace__detail-val--mono trace__detail-val--pre">{run.injectedKb}</pre>
                </div>
              )}
            </>
          ) : (
            <p className="run-replay__cleared">调试详情已清除</p>
          )}
        </details>

        <div className="run-replay__actions">
          <button
            type="button"
            className="run-replay__clear-btn"
            onClick={handleClearThisRun}
            disabled={clearing}
          >
            {clearing ? "清除中…" : "清除此 run 调试详情"}
          </button>
          <button
            type="button"
            className="run-replay__export-btn"
            onClick={() => triggerDownload(`run-${run.id}.md`, buildRunMarkdown(run), "text/markdown;charset=utf-8")}
          >
            导出 md
          </button>
          <button
            type="button"
            className="run-replay__export-btn"
            onClick={() => triggerDownload(`run-${run.id}.json`, JSON.stringify(run, null, 2), "application/json;charset=utf-8")}
          >
            导出 json
          </button>
        </div>
      </section>
    </div>
  );
}
