import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { RunListItem } from "../api/client.types";

interface Props {
  spawnId: number;
  spawnName: string | null;
  onBack: () => void;
  onSelectRun: (runId: number) => void;
}

/** Score-band color for the status dot, matching DiagnosisCatalog's health palette. */
function scoreDotColor(score: number | null): string {
  if (score == null) return "var(--text-muted, #888)";
  if (score < 4) return "var(--danger)";
  if (score < 7) return "var(--warning)";
  return "var(--success)";
}

function fmtTime(createdAt?: string | null): string {
  if (!createdAt) return "—";
  const d = new Date(createdAt);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function fmtMs(ms: number | null): string {
  return ms != null ? `${(ms / 1000).toFixed(1)}s` : "—";
}

/**
 * Per-spawn run list — DG-6: catalog row → here → RunReplay drill-through.
 * L2-internal view swapped in place of DiagnosisCatalog when a spawn is selected.
 */
export default function SpawnRunDetail({ spawnId, spawnName, onBack, onSelectRun }: Props) {
  const { t } = useTranslation();
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getRuns(spawnId, 50)
      .then((r) => { if (!cancelled) setRuns(r); })
      .catch(() => { /* best-effort */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [spawnId]);

  return (
    <div className="spawn-run-detail" data-testid="spawn-run-detail">
      <div className="spawn-run-detail__crumb">
        <button type="button" className="spawn-run-detail__back" onClick={onBack}>
          ← Diagnostics
        </button>
        <span className="spawn-run-detail__name"> / {spawnName ?? "—"}</span>
      </div>

      {loading && runs.length === 0 ? (
        <p className="spawn-run-detail__empty">{t("diag.loading", "加载中…")}</p>
      ) : runs.length === 0 ? (
        <p className="spawn-run-detail__empty">{t("diag.no_runs", "该分身还没有运行记录")}</p>
      ) : (
        <ul className="spawn-run-detail__list">
          {runs.map((r) => (
            <li
              key={r.id}
              data-testid="run-row"
              className="spawn-run-detail__row"
              style={{ cursor: "pointer" }}
              onClick={() => onSelectRun(r.id)}
            >
              <span
                className="spawn-run-detail__dot"
                style={{ background: scoreDotColor(r.overall_score) }}
                aria-hidden="true"
              />
              <span className="spawn-run-detail__time">{fmtTime(r.created_at)}</span>
              <span className="spawn-run-detail__msg">{r.user_message}</span>
              <span className="spawn-run-detail__ms">{fmtMs(r.total_ms)}</span>
              <span className="spawn-run-detail__score">
                {r.overall_score != null ? r.overall_score.toFixed(1) : "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
