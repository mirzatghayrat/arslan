import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunTimelineDto } from "../api/client.types";

interface Props {
  range: "1h" | "24h" | "all";
  onSelectSpawn: (spawnId: number | null, name: string | null) => void;
}

function sevColor(sev: string): { background: string } {
  if (sev === "red") return { background: "var(--danger)" };
  if (sev === "amber") return { background: "var(--warning)" };
  if (sev === "green") return { background: "var(--success)" };
  // "none" = no runs in this bucket: a faint recessive tint (NOT a bordered white
  // box) that reads as empty in both light and dark mode.
  return { background: "color-mix(in srgb, var(--muted-foreground) 14%, transparent)" };
}

function fmtHM(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** Per-spawn severity timeline strips (24 buckets, worst-first) — Grafana-style anomaly bands. */
export default function AnomalyTimeline({ range, onSelectSpawn }: Props) {
  const [timeline, setTimeline] = useState<RunTimelineDto | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getRunTimeline(range)
      .then((tl) => { if (!cancelled) setTimeline(tl); })
      .catch(() => { /* best-effort */ });
    return () => { cancelled = true; };
  }, [range]);

  if (!timeline) return null;

  const { buckets, spawns } = timeline;

  if (spawns.length === 0) {
    return (
      <div className="anomaly-timeline" data-testid="anomaly-timeline">
        <p className="diag-catalog__empty">暂无运行数据</p>
      </div>
    );
  }

  const mid = buckets[Math.floor(buckets.length / 2)];
  const first = buckets[0];
  const last = buckets[buckets.length - 1];

  return (
    <div className="anomaly-timeline" data-testid="anomaly-timeline">
      <div className="anomaly-timeline__header">
        <span className="anomaly-timeline__label" />
        <div className="anomaly-timeline__times">
          <span>{first ? fmtHM(first) : ""}</span>
          <span>{mid ? fmtHM(mid) : ""}</span>
          <span>{last ? fmtHM(last) : ""}</span>
        </div>
      </div>
      {spawns.map((s) => (
        <div className="anomaly-timeline__row" key={s.spawn_id ?? s.spawn_name ?? Math.random()}>
          <span
            className="anomaly-timeline__label"
            role="button"
            tabIndex={0}
            onClick={() => onSelectSpawn(s.spawn_id, s.spawn_name)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelectSpawn(s.spawn_id, s.spawn_name); }}
          >
            {s.spawn_name ?? "—"}
          </span>
          <div className="anomaly-timeline__strip">
            {s.cells.map((c, i) => (
              <div
                key={i}
                data-testid="tl-cell"
                className="anomaly-timeline__cell"
                style={sevColor(c.sev)}
                title={`${c.count} 次 · ${c.errors} 错`}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
