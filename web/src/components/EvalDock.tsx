import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { AnomalyDto } from "../api/client.types";

interface Props {
  /** Backend numeric spawn id to scope runs to. Omit for all runs (orchestrator). */
  spawnId?: number;
  /** Active conversation id — currently unused by the pill itself but kept so
   * callers don't need to branch; may inform a future scoped glance. */
  conversationId?: string;
  /** Opens the standalone full-width DiagnosisView (top-level nav section). */
  onOpenDiagnosis: () => void;
}

/**
 * Bottom-of-rail evaluation entry point — downgraded from a 3-level
 * progressive-disclosure dock (bar → slide-up catalog → expand-left replay) to
 * a lightweight health pill. The catalog/spawn-detail/replay drill-down now
 * lives entirely in the standalone DiagnosisView (top-level "诊断台" nav
 * section); this pill is just the at-a-glance signal + entry point into it.
 */
export default function EvalDock({ conversationId: _conversationId, onOpenDiagnosis }: Props) {
  const { t } = useTranslation();
  const [anomalyCount, setAnomalyCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.getRunAnomalies("1h")
      .then((anomalies: AnomalyDto[]) => { if (!cancelled) setAnomalyCount(anomalies.length); })
      .catch(() => { /* pill glance is best-effort */ });
    return () => { cancelled = true; };
  }, []);

  const hasAnomalies = anomalyCount > 0;
  const label = hasAnomalies
    ? `${t('rail.eval_label')} · ${anomalyCount} 异常`
    : t('rail.eval_label');

  return (
    <div className="eval-dock">
      <button
        type="button"
        className={`eval-dock__pill${hasAnomalies ? " eval-dock__pill--alert" : ""}`}
        onClick={onOpenDiagnosis}
      >
        {hasAnomalies && <span className="eval-dock__pill-dot" aria-hidden="true" />}
        <span className="eval-dock__pill-label">{label}</span>
      </button>
    </div>
  );
}
