import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../api/client";
import type { ProposalDetail, EvidencePair, DeltaStat } from "../api/client.types";
import { lineDiff } from "../lib/lineDiff";

interface Props {
  proposal: ProposalDetail;
  /** Opens the run-trace replay for a pair arm (candidate/baseline run id). */
  onOpenRun: (runId: number) => void;
  /** Called after a successful confirm/reject/rollback so the host can refresh. */
  onActionDone?: () => void;
}

const DIMS = ["fabrication", "identity", "completion"] as const;

/** wins/losses/ties over pairs on a verdict key ("b"=candidate win, "a"=loss). */
function tally(pairs: EvidencePair[], key: "overall" | (typeof DIMS)[number]) {
  let w = 0;
  let l = 0;
  let t = 0;
  for (const p of pairs) {
    const v = key === "overall" ? p.overall : p.per_dim?.[key];
    if (v === "b") w++;
    else if (v === "a") l++;
    else t++;
  }
  return { w, l, t, n: w + l };
}

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}

function fmtP(p: number | null | undefined): string {
  if (p == null) return "—";
  if (p < 0.001) return "<0.001";
  return p.toFixed(3);
}

/**
 * PromotionCard — the S2 "感觉真实" layer (spec §E7). Every win-rate number is
 * traceable to an evidence pair; real and synthetic corpora are rendered as TWO
 * separate blocks and NEVER merged into a single win-rate; evidence is p-value
 * tiered. Reads ONLY user_facing fields (real_delta / synthetic_delta / pairs /
 * flags / excluded_count) — it never computes a combined delta.
 */
export default function PromotionCard({ proposal, onOpenRun, onActionDone }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [staleMsg, setStaleMsg] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const ev = proposal.evidence;
  const real: DeltaStat = ev.real_delta;
  const synth: DeltaStat = ev.synthetic_delta;
  const pairs = ev.pairs ?? [];
  const flags = ev.flags ?? [];
  const tier = ev.evidence_tier ?? "weak";
  const isStale = proposal.status === "stale" || proposal.is_stale;

  // ① honest diff base: the proposal's stored base has DRIFTED when stale, so the
  // live base_prompt no longer matches base_prompt_sha — we diff against the live
  // base and warn ("base 已变更"). When not stale, base_prompt IS the gate baseline.
  const diffRows = useMemo(
    () => lineDiff(proposal.base_prompt ?? "", proposal.candidate_prompt ?? ""),
    [proposal.base_prompt, proposal.candidate_prompt],
  );

  const syntheticDriven = real.n < 3 || flags.includes("synthetic_driven");

  const tierTone =
    tier === "strong" ? "text-success" : tier === "medium" ? "text-warning" : "text-muted-foreground";
  const tierLabel =
    tier === "strong"
      ? t("evolution.card.tier_strong")
      : tier === "medium"
        ? t("evolution.card.tier_medium")
        : t("evolution.card.tier_weak");

  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setStaleMsg(true);
      } else {
        setError(String(e));
      }
    } finally {
      setBusy(false);
    }
  }

  const confirm = () =>
    act(async () => {
      const res = await api.confirmProposal(proposal.id);
      if (res.ok) {
        setDone(t("evolution.card.confirmed", { n: res.generation_level ?? "?" }));
        onActionDone?.();
      } else if ((res.reason ?? "").includes("stale")) {
        setStaleMsg(true);
      } else {
        setError(res.reason ?? "promote failed");
      }
    });

  const reject = () =>
    act(async () => {
      await api.rejectProposal(proposal.id);
      setDone(t("evolution.card.rejected_done"));
      onActionDone?.();
    });

  const rollback = () =>
    act(async () => {
      const res = await api.rollbackProposal(proposal.id);
      setDone(t("evolution.card.rolled_back", { n: res.generation_level ?? "?" }));
      onActionDone?.();
    });

  const rerun = () =>
    act(async () => {
      await api.refreshProposal(proposal.id);
      onActionDone?.();
    });

  const CorpusBlock = ({ label, d, muted }: { label: string; d: DeltaStat; muted?: boolean }) => (
    <div
      className="flex-1 min-w-[180px] rounded-lg border border-border p-3 bg-background"
      data-testid={muted ? "corpus-synthetic" : "corpus-real"}
    >
      <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground">{label}</div>
      {d.n === 0 ? (
        <div className="mt-1 text-sm text-muted-foreground">{t("evolution.card.no_real")}</div>
      ) : (
        <>
          <div className={`mt-1 text-2xl font-bold font-mono tabular-nums ${muted ? "text-foreground" : "text-primary"}`}>
            {pct(d.win_rate)}
          </div>
          <div className="mt-0.5 text-[11px] font-mono tabular-nums text-muted-foreground">
            {t("evolution.card.pairs_n", { n: d.n })} ·{" "}
            {t("evolution.card.wlt", { w: d.wins, l: d.losses, t: d.ties })}
          </div>
          <div className="text-[11px] font-mono tabular-nums text-muted-foreground">
            {t("evolution.card.p_value", { p: fmtP(d.p_value) })} · {t("evolution.card.ci", {
              lo: pct(d.ci95?.[0]),
              hi: pct(d.ci95?.[1]),
            })}
          </div>
        </>
      )}
    </div>
  );

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-4" data-testid="promotion-card">
      {/* header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-bold text-foreground truncate">
            {proposal.spawn_name ?? `#${proposal.spawn_id}`}
          </span>
          {proposal.generation_level != null && (
            <span className="text-[11px] font-mono text-muted-foreground shrink-0">
              {t("evolution.card.generation", { n: proposal.generation_level })}
            </span>
          )}
        </div>
        <div className="flex flex-col items-end gap-0.5 shrink-0">
          <span className={`text-[11px] font-mono uppercase tracking-wider ${tierTone}`} data-testid="tier-badge">
            {t("evolution.card.tier_label")}: {tierLabel}
          </span>
          {flags.includes("sequential_uncorrected") && (
            <span
              className="text-[10px] font-mono text-muted-foreground text-right max-w-[220px] leading-tight"
              data-testid="sequential-note"
            >
              {t("evolution.card.tier_sequential_note")}
            </span>
          )}
        </div>
      </div>

      {/* ③ prominent synthetic-driven banner (real corpus too thin) */}
      {syntheticDriven && (
        <div
          className="rounded-lg border border-warning bg-warning/10 px-3 py-2 text-[12px] font-mono text-warning"
          data-testid="synthetic-driven-banner"
        >
          {t("evolution.card.synthetic_driven_banner")}
        </div>
      )}

      {/* staleness */}
      {(isStale || staleMsg) && (
        <div
          className="rounded-lg border border-danger bg-danger/10 px-3 py-2 text-[12px] font-mono text-danger"
          data-testid="stale-banner"
        >
          {t("evolution.card.stale_banner")}
        </div>
      )}

      {/* ③ DUAL corpus numbers — never merged */}
      <div className="flex flex-wrap gap-3">
        <CorpusBlock label={t("evolution.card.real_corpus")} d={real} />
        <CorpusBlock label={t("evolution.card.synthetic_corpus")} d={synth} muted />
      </div>

      {/* ② per-dimension win table */}
      <div>
        <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground mb-1">
          {t("evolution.card.dim_table_title")}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px] font-mono tabular-nums">
            <thead>
              <tr className="text-muted-foreground text-left">
                <th className="font-normal py-1 pr-3"> </th>
                <th className="font-normal py-1 pr-3 text-right">{t("evolution.card.col_win")}</th>
                <th className="font-normal py-1 pr-3 text-right">{t("evolution.card.col_loss")}</th>
                <th className="font-normal py-1 pr-3 text-right">{t("evolution.card.col_tie")}</th>
                <th className="font-normal py-1 text-right">{t("evolution.card.col_n")}</th>
              </tr>
            </thead>
            <tbody>
              {DIMS.map((d) => {
                const r = tally(pairs, d);
                return (
                  <tr key={d} className="text-foreground" data-testid={`dim-row-${d}`}>
                    <td className="py-1 pr-3 text-muted-foreground">{t(`evolution.card.dim_${d}`)}</td>
                    <td className="py-1 pr-3 text-right text-success">{r.w}</td>
                    <td className="py-1 pr-3 text-right text-danger">{r.l}</td>
                    <td className="py-1 pr-3 text-right text-muted-foreground">{r.t}</td>
                    <td className="py-1 text-right">{r.n}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ① real diff */}
      <details className="rounded-lg border border-border" open>
        <summary className="cursor-pointer select-none px-3 py-2 text-[11px] font-mono uppercase tracking-wider text-muted-foreground">
          {t("evolution.card.diff_title")}
          {isStale && <span className="ml-2 text-danger">· {t("evolution.card.base_changed")}</span>}
        </summary>
        <pre className="max-h-64 overflow-auto px-3 pb-3 text-[12px] font-mono leading-5" data-testid="prompt-diff">
          {diffRows.map((row, idx) => {
            const cls =
              row.type === "add"
                ? "bg-success/10 text-success"
                : row.type === "del"
                  ? "bg-danger/10 text-danger"
                  : "text-muted-foreground";
            const sign = row.type === "add" ? "+" : row.type === "del" ? "-" : " ";
            return (
              <div key={idx} className={cls} data-diff={row.type}>
                {sign} {row.text || " "}
              </div>
            );
          })}
        </pre>
      </details>

      {/* ⑤ per-pair trace links */}
      <div>
        <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground mb-1">
          {t("evolution.card.pairs_title")}
        </div>
        <ul className="space-y-1">
          {pairs.map((p, i) => {
            const verdict =
              p.overall === "b"
                ? t("evolution.card.overall_win")
                : p.overall === "a"
                  ? t("evolution.card.overall_loss")
                  : t("evolution.card.overall_tie");
            const verdictTone =
              p.overall === "b" ? "text-success" : p.overall === "a" ? "text-danger" : "text-muted-foreground";
            return (
              <li
                key={`${p.task_hash}-${i}`}
                className="flex items-center gap-2 text-[12px] font-mono"
                data-testid="pair-row"
              >
                <span className="text-muted-foreground shrink-0">
                  {p.corpus_label === "real"
                    ? t("evolution.inbox.real_short")
                    : t("evolution.inbox.synthetic_short")}
                </span>
                <span className={`shrink-0 ${verdictTone}`}>{verdict}</span>
                {p.position_sensitive && (
                  <span className="shrink-0 text-warning" title={t("evolution.card.flag_position_sensitive")}>
                    ⚠
                  </span>
                )}
                <span className="flex-1" />
                {p.candidate_run_id != null && (
                  <button
                    type="button"
                    className="shrink-0 text-primary hover:underline"
                    data-testid="view-replay"
                    data-run-id={p.candidate_run_id}
                    onClick={() => onOpenRun(p.candidate_run_id as number)}
                  >
                    {t("evolution.card.view_replay")}
                  </button>
                )}
                {p.baseline_run_id != null && (
                  <button
                    type="button"
                    className="shrink-0 text-muted-foreground hover:text-primary hover:underline"
                    onClick={() => onOpenRun(p.baseline_run_id as number)}
                  >
                    {t("evolution.card.baseline_arm")}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      {/* ⑥ exclusion + toolset disclosure, estimate/actual */}
      <div className="space-y-0.5 text-[11px] font-mono text-muted-foreground">
        <div data-testid="exclusion-line">{t("evolution.card.exclusion", { n: ev.excluded_count ?? 0 })}</div>
        <div>{t("evolution.card.toolset_disclaimer")}</div>
        {proposal.estimate && (
          <div className="tabular-nums">
            {t("evolution.card.estimate_line", {
              judge: proposal.estimate.judge_calls,
              tokens: proposal.estimate.est_tokens,
            })}
          </div>
        )}
      </div>

      {/* ⑥b what it ACTUALLY cost — deliberately its own block, NOT a sibling line of
          the estimate above.
          🔴 The two numbers are both unreliable, in OPPOSITE directions: the estimate
          applies the optimizer's per-pair multiplier to the whole corpus and so
          OVER-counts, growing with corpus size, while this figure can UNDER-count (a
          replay arm that died before reporting usage contributes zero) and may itself be
          a character heuristic. Rendered as adjacent tabular-nums lines they read as a
          forecast-vs-outcome pair and invite a ratio, and that ratio means nothing. So:
          separate block, caveats driven by backend fields, and NO difference, ratio or
          percentage is computed anywhere — see the test that pins it. */}
      {proposal.actual && typeof proposal.actual.est_tokens === "number" && (
        <div className="space-y-0.5 text-[11px] font-mono text-muted-foreground"
          data-testid="actual-cost">
          <div className="tabular-nums">
            {t("evolution.card.actual_line", { tokens: proposal.actual.est_tokens as number })}
          </div>
          {typeof proposal.actual.dispatch_tokens === "number"
            && typeof proposal.actual.direct_tokens === "number" && (
            <div className="tabular-nums" data-testid="actual-split">
              {t("evolution.card.actual_split", {
                dispatch: proposal.actual.dispatch_tokens as number,
                direct: proposal.actual.direct_tokens as number,
              })}
            </div>
          )}
          {proposal.actual.estimated === true && (
            <div data-testid="actual-estimated">{t("evolution.card.actual_estimated")}</div>
          )}
          {typeof proposal.actual.failed_dispatches === "number"
            && (proposal.actual.failed_dispatches as number) > 0 && (
            <div data-testid="actual-incomplete">
              {t("evolution.card.actual_incomplete", {
                n: proposal.actual.failed_dispatches as number,
              })}
            </div>
          )}
          <div data-testid="not-comparable">{t("evolution.card.actual_not_comparable")}</div>
        </div>
      )}

      {/* ⑦ warn flags as chips */}
      {flags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {flags.map((f) => (
            <span
              key={f}
              className="rounded-full border border-warning/50 bg-warning/10 px-2 py-0.5 text-[10px] font-mono text-warning"
              data-testid="flag-chip"
            >
              {t(`evolution.card.flag_${f}`, { defaultValue: f })}
            </span>
          ))}
        </div>
      )}

      {/* actions */}
      {done ? (
        <div className="text-[12px] font-mono text-success" data-testid="action-done">
          {done}
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {proposal.status === "promoted" ? (
            <button
              type="button"
              className="px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg border border-danger text-danger hover:bg-danger/10 transition-all disabled:opacity-50"
              disabled={busy}
              onClick={rollback}
              data-testid="rollback-btn"
            >
              {t("evolution.card.rollback")}
            </button>
          ) : isStale ? (
            <button
              type="button"
              className="px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg bg-primary hover:bg-primary-hover text-primary-foreground transition-all disabled:opacity-50"
              disabled={busy}
              onClick={rerun}
              data-testid="rerun-btn"
            >
              {t("evolution.card.rerun_gate")}
            </button>
          ) : (
            <>
              <button
                type="button"
                className={
                  tier === "weak"
                    ? "px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg border border-border text-muted-foreground hover:text-foreground hover:border-primary/50 transition-all disabled:opacity-50"
                    : "px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg bg-primary hover:bg-primary-hover text-primary-foreground transition-all disabled:opacity-50"
                }
                disabled={busy || !proposal.gate_passed}
                onClick={confirm}
                data-testid="confirm-btn"
              >
                {t("evolution.card.confirm")}
              </button>
              {tier === "weak" && (
                <span className="text-[11px] font-mono text-muted-foreground" data-testid="weak-hint">
                  {t("evolution.card.wait_hint")}
                </span>
              )}
              <button
                type="button"
                className="px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg border border-border text-muted-foreground hover:text-foreground transition-all disabled:opacity-50"
                disabled={busy}
                onClick={reject}
                data-testid="reject-btn"
              >
                {t("evolution.card.reject")}
              </button>
            </>
          )}
        </div>
      )}

      {error && (
        <div className="text-[12px] font-mono text-danger" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
