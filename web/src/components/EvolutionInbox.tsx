import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../api/client";
import type { EvolveRepeatRefusal } from "../api/client";
import type {
  ProposalListItem,
  ProposalDetail,
  EvolveEstimate,
  SpawnSummary,
  SpawnDiagnosis,
} from "../api/client.types";
import PromotionCard from "./PromotionCard";
import { EvolutionEligibilityPanel } from "./EvolutionEligibilityPanel";

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
/** How long the panel follows an attempt before admitting it lost track. Attempts take
 * minutes; last_attempts keeps only the newest few, so on a busy spawn ours can be pushed
 * out and never observed. Saying so beats "running…" forever. */
const WATCH_GIVE_UP_MS = 10 * 60 * 1000;

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

  // P5/P9 — the spend gate's structured 409, rendered as a confirmation.
  //
  // 🔴 Both of these are BOUND TO THEIR SPAWN. A refusal describes one spawn's attempt,
  // and "Run anyway" spends money; if it survived a spawn switch, consent given for A
  // would force-bypass B's own fail-closed gate while the dialog still described A.
  // Likewise `watching` is an attempt id that can only ever appear in ITS spawn's
  // diagnosis, so following it against another spawn polls forever for something that
  // cannot arrive. Storing the spawn alongside makes both impossible to get wrong.
  const [refusal, setRefusal] = useState<{ spawnId: number; data: EvolveRepeatRefusal } | null>(null);
  // P7 — the attempt this panel is currently following, tracked BY ID.
  const [watching, setWatching] = useState<{ spawnId: number; attemptId: number } | null>(null);

  // per-spawn eligibility diagnosis (read-only; keyed off runSpawn).
  const [diag, setDiag] = useState<SpawnDiagnosis | null>(null);
  useEffect(() => {
    if (runSpawn === "") {
      setDiag(null);
      return;
    }
    let alive = true;
    api
      .getEvolutionDiagnosis(Number(runSpawn))
      .then((d) => alive && setDiag(d))
      .catch(() => alive && setDiag(null));
    return () => {
      alive = false;
    };
  }, [runSpawn]);

  // P7 — the missing feedback loop. Before this, the panel fetched once on mount with no
  // polling and no WS event, so a click produced "Enqueued · attempt N" and then nothing
  // ever changed: the attempt finished minutes later in silence, and a refusal
  // (skipped_budget) or a gate failure was never shown at all. A button that does nothing
  // visible is a button people click again — which is exactly what was reported.
  //
  // Keyed on the attempt id we launched, NOT on last_attempts[0]: that slot can be taken
  // by a DIFFERENT attempt (the auto watcher runs on the same spawn), which would make us
  // attribute someone else's outcome to this click, and can also never settle.
  useEffect(() => {
    if (watching == null) return;
    const { spawnId, attemptId } = watching;
    let alive = true;
    let delay = 2000;
    let elapsed = 0;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      if (!alive) return;
      try {
        // poll the attempt's OWN spawn, not whatever is selected now
        const d = await api.getEvolutionDiagnosis(spawnId);
        if (!alive) return;
        if (spawnId === runSpawn) setDiag(d);
        const mine = d.last_attempts?.find((a) => a.id === attemptId);
        if (mine && mine.outcome) {
          setEnqueued(
            t(`evolution.inbox.outcome_${mine.outcome}`, {
              id: mine.id,
              reason: mine.reason || "",
              // an outcome we have no copy for must not render a raw key
              defaultValue: t("evolution.inbox.watch_lost", { id: mine.id }),
            }),
          );
          setWatching(null);
          return;
        }
      } catch {
        // a failed poll is not worth surfacing — the next tick retries
      }
      // GIVE UP eventually. Without this the panel says "running…" forever whenever the
      // attempt never lands in last_attempts (it keeps only the newest few, so a busy
      // spawn can push ours out), and `watch_lost` — copy translated into six locales
      // for exactly this case — would be unreachable.
      elapsed += delay;
      if (elapsed >= WATCH_GIVE_UP_MS) {
        setEnqueued(t("evolution.inbox.watch_lost", { id: attemptId }));
        setWatching(null);
        return;
      }
      delay = Math.min(delay * 1.5, 15000);   // back off; attempts take minutes
      timer = setTimeout(poll, delay);
    };

    timer = setTimeout(poll, delay);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watching]);

  async function load() {
    setError(null);
    try {
      const [proposals, spawns] = await Promise.all([
        api.getEvolutionProposals(),
        api.listSpawns().catch(() => [] as SpawnSummary[]),
      ]);
      setRows(proposals);
      setNames(Object.fromEntries(spawns.map((s) => [s.id, s.name])));
      // P8 — make the eligibility panel reachable on FIRST PAINT. It already existed, but
      // it only rendered once `diag` was loaded, and `diag` only loaded once the user
      // picked a spawn from a control labelled "Run evolution…" — a control whose whole
      // affordance says "trigger", not "inspect". So the answer to "why are there no
      // proposals?" was sitting behind the button the confused user was not going to press.
      setRunSpawn((cur) => (cur === "" && spawns.length > 0 ? spawns[0].id : cur));
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

  async function enqueue(force = false) {
    if (runSpawn === "") return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.runEvolve(runSpawn, { force });
      setRefusal(null);
      setEnqueued(
        res.attempt_id != null
          ? t("evolution.inbox.enqueued", { id: res.attempt_id })
          : t("evolution.inbox.already_running"),
      );
      // P7 — follow THIS attempt. attempt_id is null when one is already running
      // (concurrency = 1); there is nothing of ours to follow in that case.
      setWatching(res.attempt_id != null ? { spawnId: runSpawn, attemptId: res.attempt_id } : null);
      setEstimate(null);
    } catch (e) {
      // P9 — the spend gate. Render the BACKEND's facts; do not compose an explanation
      // here, or the dialog will drift from what the server actually decided.
      if (e instanceof ApiError && e.status === 409 && e.detail) {
        setRefusal({ spawnId: runSpawn, data: e.detail as EvolveRepeatRefusal });
      } else {
        setError(String(e));
      }
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
              // 🔴 the refusal authorizes spending on ONE spawn. Carrying it across a
              // switch would let "Run anyway" force-bypass a different spawn's gate.
              setRefusal(null);
              setWatching(null);
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
              onClick={() => enqueue(false)}
              data-testid="enqueue-btn"
            >
              {t("evolution.inbox.enqueue")}
            </button>
          </div>
        )}
        {refusal && refusal.spawnId === runSpawn && (
          <div
            className="rounded-lg border border-warning/40 bg-warning/5 p-3 space-y-2 text-[12px] font-mono"
            role="alertdialog"
            aria-labelledby="evo-confirm-title"
            data-testid="repeat-confirm"
          >
            <div id="evo-confirm-title" className="font-bold text-warning">
              {t("evolution.inbox.confirm_title")}
            </div>
            <div className="text-muted-foreground">
              {t("evolution.inbox.confirm_body", {
                id: refusal.data.last_attempt_id,
                reason: refusal.data.last_reason,
              })}
            </div>
            {refusal.data.est_tokens != null && (
              <div className="text-muted-foreground tabular-nums">
                {t("evolution.inbox.confirm_cost", { tokens: refusal.data.est_tokens })}
              </div>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                className="px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg border border-border text-muted-foreground hover:text-foreground transition-all"
                onClick={() => setRefusal(null)}
                data-testid="repeat-cancel"
              >
                {t("evolution.inbox.confirm_cancel")}
              </button>
              <button
                type="button"
                className="px-3 py-1.5 text-[11px] font-bold font-sans uppercase rounded-lg bg-warning/80 hover:bg-warning text-background transition-all disabled:opacity-50"
                disabled={busy}
                onClick={() => enqueue(true)}
                data-testid="repeat-force"
              >
                {t("evolution.inbox.confirm_run")}
              </button>
            </div>
          </div>
        )}
        {watching != null && watching.spawnId === runSpawn && (
          <div className="text-[12px] font-mono text-muted-foreground" data-testid="watching-msg">
            {t("evolution.inbox.watching", { id: watching.attemptId })}
          </div>
        )}
        {enqueued && watching == null && (
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

      {/* P8 — the eligibility panel renders whenever a spawn is selected, not only when
          the GLOBAL proposal list is empty. Gating it on that list meant a user holding
          one proposal for spawn A could never find out why spawn B had none. */}
      {diag && <EvolutionEligibilityPanel diag={diag} />}

      {rows == null ? (
        <div className="text-[12px] font-mono text-muted-foreground">{t("evolution.inbox.loading")}</div>
      ) : rows.length === 0 ? (
        <div className="space-y-2">
          <div className="text-[12px] font-mono text-muted-foreground">{t("evolution.inbox.empty")}</div>
          {!diag && (
            <div className="text-[12px] font-mono text-muted-foreground">{t("evolution.diag.pick_spawn")}</div>
          )}
        </div>
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
