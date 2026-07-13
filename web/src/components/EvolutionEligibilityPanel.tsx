import { useTranslation } from "react-i18next";
import type { SpawnDiagnosis } from "../api/client.types";

/**
 * EvolutionEligibilityPanel (E9-b Task 4d) — the "why no proposals yet" panel shown in the
 * evolution inbox empty-state for a selected spawn. Renders the shared, read-only diagnosis:
 * a localized verdict sentence (from the machine `verdict_code` + `verdict_params`) plus an
 * honest "blocker chain" (replayable N/total, holdout real→effective, backoff, last attempt).
 *
 * Honesty: a thin real holdout is NOT a wall — the panel shows it fills to `effective_holdout`
 * via the synthetic top-up on the next evolve. Nothing here fabricates a promotion.
 */
export function EvolutionEligibilityPanel({ diag }: { diag: SpawnDiagnosis }) {
  const { t } = useTranslation();
  const verdict = t(
    `evolution.diag.verdict_${diag.verdict_code}`,
    diag.verdict_params as Record<string, unknown>,
  );
  const last = diag.last_attempts[0];
  return (
    <div
      className="rounded-lg border border-border bg-background p-3 text-[12px] font-mono"
      data-testid="eligibility-panel"
    >
      <div className="mb-2 font-semibold text-foreground">{t("evolution.diag.title")}</div>
      <div className="mb-2 text-foreground" data-testid="eligibility-verdict">
        {verdict}
      </div>
      <ul className="space-y-1 text-muted-foreground">
        <li>
          {t("evolution.diag.chain_replayable", {
            replayable: diag.replayable,
            total_scored: diag.total_scored,
          })}
        </li>
        <li>
          {t("evolution.diag.chain_holdout", {
            real_holdout: diag.real_holdout,
            effective_holdout: diag.effective_holdout,
            min: diag.min_holdout_n,
          })}
        </li>
        <li>
          {t("evolution.diag.chain_backoff", {
            count_since: diag.count_since_last_attempt,
            threshold: diag.threshold,
          })}
        </li>
        <li>
          {last
            ? t("evolution.diag.chain_last_attempt", {
                outcome: last.outcome ?? "in-flight",
                reason: last.reason || "—",
              })
            : t("evolution.diag.chain_none")}
        </li>
        {!diag.auto_on && <li>{t("evolution.diag.auto_off")}</li>}
      </ul>
    </div>
  );
}

export default EvolutionEligibilityPanel;
