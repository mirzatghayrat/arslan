import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RecapDto } from "../api/client.types";

interface Props {
  /** Backend numeric spawn id (spawn section) — unused by the recap timeline. */
  spawnId?: number;
  /** Active conversation id — the recap is scoped to it. Empty → dock hidden. */
  conversationId?: string;
  /** Opens the standalone full-width DiagnosisView (top-level nav section). */
  onOpenDiagnosis: () => void;
}

const KIND_LABEL: Record<string, string> = {
  distill: "蒸馏", memory: "记忆", skill: "技能", evolution: "进化", invite: "邀请",
};

function scoreColor(s: number | null | undefined): string {
  if (s == null) return "var(--muted-foreground)";
  if (s >= 7) return "var(--success)";
  if (s >= 4) return "var(--warning)";
  return "var(--danger)";
}

/** Skills/evolution read as "capability" changes → warning accent; the softer
 * growth signals (distill/memory/invite) use the primary accent. */
function kindColor(kind: string): string {
  return kind === "skill" || kind === "evolution" ? "var(--warning)" : "var(--primary)";
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * In-rail conversation recap — the scoped timeline of THIS conversation's runs
 * (with scores) mixed with Arslan's growth events (蒸馏/记忆/技能/进化/邀请),
 * newest first. Replaces the earlier health pill; the full-width catalog/replay
 * drill-down still lives in the standalone DiagnosisView (Diagnostics ↗ link).
 */
export default function EvalDock({ conversationId, onOpenDiagnosis }: Props) {
  const [recap, setRecap] = useState<RecapDto | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!conversationId) { setRecap(null); return; }
    let cancelled = false;
    api.getConversationRecap(conversationId)
      .then((r) => { if (!cancelled) setRecap(r); })
      .catch(() => { if (!cancelled) setRecap(null); });
    return () => { cancelled = true; };
  }, [conversationId]);

  if (!conversationId) return null;

  const items = recap?.items ?? [];
  const s = recap?.summary;

  return (
    <div className={`recap-dock${open ? " recap-dock--open" : ""}`}>
      <div
        className="recap-dock__head"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen((o) => !o); } }}
      >
        <span className="recap-dock__chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
        <span className="recap-dock__title">本对话 · 回顾</span>
        {s && (
          <span className="recap-dock__summary-inline">
            {s.run_count} 运行 · 均分 {s.avg_score ?? "—"} · 成长 {s.growth_count}
          </span>
        )}
        <button
          type="button"
          className="recap-dock__link"
          onClick={(e) => { e.stopPropagation(); onOpenDiagnosis(); }}
        >
          Diagnostics ↗
        </button>
      </div>
      {open && (items.length === 0 ? (
        <div className="recap-dock__empty">本对话还没有运行 / 成长记录</div>
      ) : (
        <ul className="recap-timeline">
          {items.map((it, i) => (
            <li
              key={i}
              className="recap-item"
              data-testid="recap-item"
              onClick={it.kind === "run" ? onOpenDiagnosis : undefined}
              style={{ cursor: it.kind === "run" ? "pointer" : "default" }}
            >
              {it.kind === "run" ? (
                <div className="recap-item__body">
                  <span className="recap-item__tag" style={{ color: scoreColor(it.overall_score) }}>
                    运行 · {it.overall_score != null ? it.overall_score.toFixed(1) : "评分中"}
                  </span>
                  <span className="recap-item__title">{it.spawn_name ?? "分身"}</span>
                  {it.user_message && <span className="recap-item__sub">{it.user_message}</span>}
                </div>
              ) : (
                <div className="recap-item__body">
                  <span className="recap-item__tag" style={{ color: kindColor(it.kind) }}>
                    {KIND_LABEL[it.kind] ?? it.kind}
                  </span>
                  <span className="recap-item__title">{it.summary ?? ""}</span>
                </div>
              )}
              <span className="recap-item__time">{fmtTime(it.created_at)}</span>
            </li>
          ))}
        </ul>
      ))}
    </div>
  );
}
