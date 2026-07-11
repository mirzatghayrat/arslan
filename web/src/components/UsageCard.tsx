import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { UsageSummary } from "../api/client.types";
import { fmtTok, fmtUsd } from "../lib/usageFormat";
import { Sparkline } from "./DiagnosisCatalog";

type RangeKey = "24h" | "7d" | "30d";
const RANGES: RangeKey[] = ["24h", "7d", "30d"];

/**
 * S3-M3 Diagnostics 用量卡 — fleet-wide cost visibility (GET /usage/summary).
 * provider×model×scope table + daily-tokens sparkline + the honest 未计入
 * footnote (call sites that don't feed the ledger yet). Visibility only, no
 * budgets. Follows the DiagnosisCatalog visual idiom (range tabs + diag-table).
 *
 * Honesty rules mirrored from the backend: ≈ marks rows whose tokens include
 * estimates; usd == null renders "—", never $0 (unknown ≠ free).
 */
export default function UsageCard() {
  const { t } = useTranslation();
  const [range, setRange] = useState<RangeKey>("7d");
  const [summary, setSummary] = useState<UsageSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getUsageSummary(range)
      .then((s) => { if (!cancelled) setSummary(s); })
      .catch(() => { /* dashboard is best-effort */ });
    return () => { cancelled = true; };
  }, [range]);

  const rows = summary?.rows ?? [];
  const daily = summary?.daily ?? [];

  return (
    <div className="usage-card" data-testid="usage-card">
      <div className="usage-card__head">
        <h3 className="usage-card__title">{t("usage.title")}</h3>
        <div className="diag-catalog__range" role="tablist" aria-label="usage range">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              role="tab"
              aria-selected={range === r}
              data-testid={`usage-range-${r}`}
              className={`diag-catalog__range-btn${range === r ? " diag-catalog__range-btn--active" : ""}`}
              onClick={() => setRange(r)}
            >
              {t(`usage.range.${r}`)}
            </button>
          ))}
        </div>
      </div>

      {daily.length > 0 && (
        <div className="usage-card__daily" data-testid="usage-daily-spark">
          <span className="usage-card__daily-label">{t("usage.daily")}</span>
          <span className="usage-card__spark">
            <Sparkline points={daily.map((d) => d.tokens_total)} />
          </span>
        </div>
      )}

      {rows.length === 0 ? (
        <p className="diag-catalog__empty">{t("usage.empty")}</p>
      ) : (
        <table className="diag-table usage-card__table">
          <thead>
            <tr>
              <th>{t("usage.col.provider")}</th>
              <th>{t("usage.col.model")}</th>
              <th>{t("usage.col.scope")}</th>
              <th>{t("usage.col.tokens")}</th>
              <th>{t("usage.col.usd")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} data-testid="usage-row">
                <td>{r.provider ?? "—"}</td>
                <td className="diag-table__model">{r.model ?? "—"}</td>
                <td>{r.scope}</td>
                <td className="usage-card__num">
                  {r.estimated_any ? "≈ " : ""}{fmtTok(r.tokens_total)}
                </td>
                <td className="usage-card__num">{r.usd != null ? fmtUsd(r.usd) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {summary != null && summary.not_covered.length > 0 && (
        <details className="usage-card__notcovered" data-testid="usage-notcovered">
          <summary>{t("usage.notCovered")} · {summary.not_covered.length}</summary>
          <div className="usage-card__notcovered-list">{summary.not_covered.join(" · ")}</div>
        </details>
      )}
    </div>
  );
}
