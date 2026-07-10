import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type {
  ProposalListItem,
  ProposalDetail,
  EvolveEstimate,
  SpawnSummary,
} from "../api/client.types";
import PromotionCard from "./PromotionCard";

interface Props {
  /** Opens the run-trace replay for a pair arm (wired to DiagnosisView's RunReplay). */
  onOpenRun: (runId: number) => void;
}

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}

const STATUS_TONE: Record<string, string> = {
  open: "text-primary",
  promoted: "text-success",
  rejected: "text-muted-foreground",
  stale: "text-danger",
  proposed: "text-primary",
};

/**
 * EvolutionInbox — the "进化" tab (spec §E7). Lists proposals with their dual-corpus
 * delta summary + tier + status; clicking one opens its full PromotionCard. A per-spawn
 * "运行进化" affordance shows the honest cost estimate first, then enqueues the background job.
 */
export default function EvolutionInbox({ onOpenRun }: Props) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ProposalListItem[] | null>(null);
  const [names, setNames] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ProposalDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // run-evolution affordance state
  const [runSpawn, setRunSpawn] = useState<number | "">("");
  const [estimate, setEstimate] = useState<EvolveEstimate | null>(null);
  const [enqueued, setEnqueued] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setError(null);
    try {
      const [proposals, spawns] = await Promise.all([
        api.getEvolutionProposals(),
        api.listSpawns().catch(() => [] as SpawnSummary[]),
      ]);
      setRows(proposals);
      setNames(Object.fromEntries(spawns.map((s) => [s.id, s.name])));
    } catch (e) {
      setError(String(e));
      setRows([]);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openCard(id: number) {
    setLoadingDetail(true);
    setError(null);
    try {
      setSelected(await api.getProposalDetail(id));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingDetail(false);
    }
  }

  async function fetchEstimate() {
    if (runSpawn === "") return;
    setBusy(true);
    setError(null);
    setEnqueued(null);
    try {
      setEstimate(await api.getEvolveEstimate(runSpawn));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function enqueue() {
    if (runSpawn === "") return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.runEvolve(runSpawn);
      setEnqueued(
        res.attempt_id != null
          ? t("evolution.inbox.enqueued", { id: res.attempt_id })
          : t("evolution.inbox.already_running"),
      );
      setEstimate(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (selected) {
    return (
      <div className="space-y-3" data-testid="evolution-inbox">
        <button
          type="button"
          className="text-[11px] font-mono text-muted-foreground hover:text-primary"
          onClick={() => {
            setSelected(null);
            load();
          }}
        >
          ← {t("evolution.inbox.back")}
        </button>
        <PromotionCard
          proposal={selected}
          onOpenRun={onOpenRun}
          onActionDone={() => {
            // refresh detail + list after an action
            openCard(selected.id);
            load();
          }}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="evolution-inbox">
      <h3 className="text-sm font-bold text-foreground">{t("evolution.inbox.title")}</h3>

      {/* per-spawn run-evolution affordance */}
      <div className="rounded-lg border border-border bg-card p-3 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="rounded-lg border border-border bg-background px-2 py-1.5 text-[12px] font-mono text-foreground"
            value={runSpawn}
            onChange={(e) => {
              setRunSpawn(e.target.value ? Number(e.target.value) : "");
              setEstimate(null);
              setEnqueued(null);
            }}
            aria-label={t("evolution.inbox.run_evolution")}
          >
            <option value="">{t("evolution.inbox.run_evolution")}…</option>
            {Object.entries(names).map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg border border-border text-muted-foreground hover:text-foreground hover:border-primary/50 transition-all disabled:opacity-50"
            disabled={busy || runSpawn === ""}
            onClick={fetchEstimate}
            data-testid="estimate-btn"
          >
            {t("evolution.inbox.estimate_title")}
          </button>
        </div>
        {estimate && (
          <div className="text-[11px] font-mono tabular-nums text-muted-foreground space-y-1" data-testid="estimate-box">
            <div>
              {t("evolution.card.estimate_line", {
                judge: estimate.judge_calls,
                tokens: estimate.est_tokens,
              })}
            </div>
            <div>
              {t("evolution.inbox.estimate_detail", {
                pairs: estimate.pairs,
                dispatches: estimate.dispatches,
              })}
            </div>
            <button
              type="button"
              className="mt-1 px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg bg-primary hover:bg-primary-hover text-primary-foreground transition-all disabled:opacity-50"
              disabled={busy}
              onClick={enqueue}
              data-testid="enqueue-btn"
            >
              {t("evolution.inbox.enqueue")}
            </button>
          </div>
        )}
        {enqueued && (
          <div className="text-[12px] font-mono text-success" data-testid="enqueued-msg">
            {enqueued}
          </div>
        )}
      </div>

      {error && (
        <div className="text-[12px] font-mono text-danger" role="alert">
          {error}
        </div>
      )}

      {rows == null ? (
        <div className="text-[12px] font-mono text-muted-foreground">{t("evolution.inbox.loading")}</div>
      ) : rows.length === 0 ? (
        <div className="text-[12px] font-mono text-muted-foreground">{t("evolution.inbox.empty")}</div>
      ) : (
        <ul className="space-y-2">
          {rows.map((p) => {
            const tier = p.evidence_tier ?? "weak";
            const tierTone =
              tier === "strong" ? "text-success" : tier === "medium" ? "text-warning" : "text-muted-foreground";
            return (
              <li key={p.id}>
                <button
                  type="button"
                  className="w-full text-left rounded-lg border border-border bg-card hover:border-primary/50 p-3 transition-colors"
                  onClick={() => openCard(p.id)}
                  disabled={loadingDetail}
                  data-testid="inbox-row"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-bold text-foreground truncate">
                      {names[p.spawn_id] ?? `#${p.spawn_id}`}
                    </span>
                    <span className={`text-[10px] font-mono uppercase tracking-wider ${STATUS_TONE[p.status] ?? "text-muted-foreground"}`}>
                      {t(`evolution.inbox.status_${p.status}`, { defaultValue: p.status })}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] font-mono tabular-nums text-muted-foreground">
                    <span>
                      {t("evolution.inbox.real_short")}: {p.real_delta && p.real_delta.n > 0 ? pct(p.real_delta.win_rate) : "—"}
                      {p.real_delta ? ` (${p.real_delta.n})` : ""}
                    </span>
                    <span>
                      {t("evolution.inbox.synthetic_short")}: {p.synthetic_delta && p.synthetic_delta.n > 0 ? pct(p.synthetic_delta.win_rate) : "—"}
                      {p.synthetic_delta ? ` (${p.synthetic_delta.n})` : ""}
                    </span>
                    <span className={tierTone}>{t(`evolution.card.tier_${tier}`)}</span>
                    {p.created_at && <span>{p.created_at.slice(0, 10)}</span>}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
