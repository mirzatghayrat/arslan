import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { RunCatalogDto, AnomalyDto } from "../api/client.types";

interface Props {
  onClose: () => void;
  onSelectSpawn: (spawnId: number | null, name: string | null) => void;
  spawnId?: number;
  conversationId?: string;
  /** Narrow container (e.g. mobile-width DiagnosisView) — render cards instead of a table. */
  narrow?: boolean;
}

type RangeKey = "1h" | "24h" | "all";

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "1h", label: "近1h" },
  { key: "24h", label: "24h" },
  { key: "all", label: "全部" },
];

/** Color a metric cell by fleet/spawn health so RED problems pop out of the table. */
function healthColor(health: string): string {
  if (health === "red") return "var(--danger)";
  if (health === "amber") return "var(--warning)";
  return "var(--success)";
}

function fmtTokens(sum: number): string {
  return sum >= 1000 ? `约 ${Math.round(sum / 1000)}k` : `约 ${sum}`;
}

function fmtP95(ms: number | null): string {
  return ms != null ? `${(ms / 1000).toFixed(1)}s` : "—";
}

/** Small ring donut showing avg_score/10 as an arc, colored by health. */
function HealthRing({ score, health }: { score: number | null; health: string }) {
  const r = 8;
  const c = 2 * Math.PI * r;
  const frac = (score ?? 0) / 10;
  const color = healthColor(health);
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" className="cat-ring" aria-hidden="true">
      <circle cx="11" cy="11" r={r} fill="none" stroke="var(--border)" strokeWidth="3" />
      <circle
        cx="11" cy="11" r={r} fill="none"
        stroke={color} strokeWidth="3"
        strokeDasharray={`${frac * c} ${c}`}
        transform="rotate(-90 11 11)"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Tiny bar sparkline for the score trend. */
function Sparkline({ points }: { points: number[] }) {
  if (points.length === 0) return <span className="cat-spark cat-spark--empty">—</span>;
  const max = Math.max(...points, 10);
  return (
    <span className="cat-spark" aria-hidden="true">
      {points.map((p, i) => (
        <span
          key={i}
          className="cat-spark__bar"
          style={{ height: `${Math.max(8, Math.round((p / max) * 100))}%` }}
        />
      ))}
    </span>
  );
}

/** Small severity dot — red for hard failures, amber for warnings. */
function SeverityDot({ severity }: { severity: string }) {
  const color = severity === "red" ? "var(--danger)" : "var(--warning)";
  return <span className="anomaly-row__dot" style={{ background: color }} aria-hidden="true" />;
}

export default function DiagnosisCatalog({ onSelectSpawn, narrow }: Props) {
  const { t } = useTranslation();
  const [range, setRange] = useState<RangeKey>("1h");
  const [catalog, setCatalog] = useState<RunCatalogDto | null>(null);
  const [anomalies, setAnomalies] = useState<AnomalyDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [anomOpen, setAnomOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([api.getRunCatalog(range), api.getRunAnomalies(range)])
      .then(([cat, anom]) => {
        if (cancelled) return;
        setCatalog(cat);
        setAnomalies(anom);
      })
      .catch(() => { /* dashboard is best-effort */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [range]);

  const fleet = catalog?.fleet ?? null;
  const spawns = catalog?.spawns ?? [];

  return (
    <div className="diag-catalog" data-testid="diagnosis-catalog">
      <div className="diag-catalog__range" role="tablist" aria-label="range">
        {RANGES.map((r) => (
          <button
            key={r.key}
            type="button"
            role="tab"
            aria-selected={range === r.key}
            className={`diag-catalog__range-btn${range === r.key ? " diag-catalog__range-btn--active" : ""}`}
            onClick={() => setRange(r.key)}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div className={`diag-catalog__cards${narrow ? " diag-catalog__cards--narrow" : ""}`}>
        <div className="diag-card">
          <div className="diag-card__label">运行数</div>
          <div className="diag-card__value">{fleet?.run_count ?? "—"}</div>
        </div>
        <div className="diag-card">
          <div className="diag-card__label">错误率</div>
          <div className="diag-card__value">
            {fleet ? `${Math.round(fleet.error_ratio * 100)}%` : "—"}
          </div>
        </div>
        <div className="diag-card">
          <div className="diag-card__label">P95</div>
          <div className="diag-card__value">{fleet ? fmtP95(fleet.p95_ms) : "—"}</div>
        </div>
        <div className="diag-card">
          <div className="diag-card__label">达标率</div>
          <div className="diag-card__value">
            {fleet ? `${fleet.pass_rate ?? "—"}%` : "—"}
          </div>
        </div>
        <div className="diag-card">
          <div className="diag-card__label">tokens</div>
          <div className="diag-card__value">{fleet ? fmtTokens(fleet.tokens_sum) : "—"}</div>
        </div>
      </div>

      {anomalies.length > 0 ? (
        <div
          className="diag-catalog__anomalies"
          data-testid="anomaly-badge"
          role="button"
          tabIndex={0}
          onClick={() => setAnomOpen((o) => !o)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setAnomOpen((o) => !o); }}
        >
          异常 · 断言 {anomalies.length}
          <span className={`diag-catalog__anomalies-chevron${anomOpen ? " diag-catalog__anomalies-chevron--open" : ""}`}>▾</span>
        </div>
      ) : (
        <div className="diag-catalog__anomalies diag-catalog__anomalies--empty" data-testid="anomaly-badge">
          无异常
        </div>
      )}

      {anomOpen && anomalies.length > 0 && (
        <div className="anomaly-panel" data-testid="anomaly-panel">
          {anomalies.map((a, i) => (
            <div className="anomaly-row" key={i}>
              <SeverityDot severity={a.severity} />
              <div className="anomaly-row__body">
                <div className="anomaly-row__title">{a.title}</div>
                <div className="anomaly-row__detail">{a.detail}</div>
                {a.since && <div className="anomaly-row__since">{a.since}</div>}
              </div>
              <button
                type="button"
                className="anomaly-row__jump"
                onClick={() => onSelectSpawn(a.spawn_id, a.spawn_name)}
              >
                查 →
              </button>
            </div>
          ))}
        </div>
      )}

      {loading && spawns.length === 0 ? (
        <p className="diag-catalog__empty">加载中…</p>
      ) : spawns.length === 0 ? (
        <p className="diag-catalog__empty">{t("eval.empty", "还没有运行记录")}</p>
      ) : narrow ? (
        <div className="diag-cards">
          {spawns.map((s) => (
            <div
              key={s.spawn_id ?? s.spawn_name ?? Math.random()}
              data-testid="cat-card"
              className="diag-card-row"
              onClick={() => onSelectSpawn(s.spawn_id, s.spawn_name)}
            >
              <div className="diag-card-row__top">
                <HealthRing score={s.avg_score} health={s.health} />
                <div className="diag-card-row__name">
                  <div className="diag-table__spawn">{s.spawn_name ?? "—"}</div>
                  <div className="diag-table__model">{s.model ?? ""}</div>
                </div>
                <div className="diag-card-row__score">
                  {s.avg_score != null ? s.avg_score.toFixed(1) : "—"}
                </div>
              </div>
              <div className="diag-card-row__stat" style={{ color: healthColor(s.health) }}>
                {s.run_count} run · 达标 {s.pass_rate ?? "—"}% · P95 {fmtP95(s.p95_ms)}
              </div>
              <div className="diag-card-row__bottom">
                <span>{fmtTokens(s.tokens_sum)}</span>
                <Sparkline points={s.score_trend} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <table className="diag-table">
          <thead>
            <tr>
              <th>健康度</th>
              <th>分身</th>
              <th>运行数</th>
              <th>错误率</th>
              <th>P95</th>
              <th>达标率</th>
              <th>tokens</th>
              <th>趋势</th>
            </tr>
          </thead>
          <tbody>
            {spawns.map((s) => (
              <tr
                key={s.spawn_id ?? s.spawn_name ?? Math.random()}
                data-testid="cat-row"
                style={{ cursor: "pointer" }}
                onClick={() => onSelectSpawn(s.spawn_id, s.spawn_name)}
              >
                <td className="diag-table__health">
                  <HealthRing score={s.avg_score} health={s.health} />
                  <span>{s.avg_score != null ? s.avg_score.toFixed(1) : "—"}</span>
                </td>
                <td>
                  <div className="diag-table__spawn">{s.spawn_name ?? "—"}</div>
                  <div className="diag-table__model">{s.model ?? ""}</div>
                </td>
                <td>{s.run_count}</td>
                <td style={{ color: healthColor(s.health) }}>
                  {Math.round(s.error_ratio * 100)}%
                </td>
                <td style={{ color: healthColor(s.health) }}>{fmtP95(s.p95_ms)}</td>
                <td style={{ color: healthColor(s.health) }}>
                  {s.pass_rate ?? "—"}%
                </td>
                <td>{fmtTokens(s.tokens_sum)}</td>
                <td><Sparkline points={s.score_trend} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
