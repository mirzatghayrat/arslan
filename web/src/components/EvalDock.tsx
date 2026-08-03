import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { ConversationUsage, RecapDto } from "../api/client.types";
import { fmtTok, fmtUsd } from "../lib/usageFormat";
import { useArslanStore } from "../stores/arslanStore";
import { HeartPulse } from "lucide-react";

interface Props {
  /** Backend numeric spawn id (spawn section) — unused by the recap timeline. */
  spawnId?: number;
  /** Active conversation id — the recap is scoped to it. Empty → dock hidden. */
  conversationId?: string;
  /** Opens the standalone full-width DiagnosisView (top-level nav section). */
  onOpenDiagnosis: () => void;
}

const KIND_LABEL_KEY: Record<string, string> = {
  distill: "eval.kind_distill",
  memory: "eval.kind_memory",
  skill: "eval.kind_skill",
  evolution: "eval.kind_evolution",
  invite: "eval.kind_invite",
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
  const { t } = useTranslation();
  const [recap, setRecap] = useState<RecapDto | null>(null);
  const [usage, setUsage] = useState<ConversationUsage | null>(null);
  const [open, setOpen] = useState(false);
  // S3-M3: refetch the cumulative usage after every finalized turn — lastMessageId
  // bumps exactly when a stream_end (or message) frame lands in the store.
  const lastMessageId = useArslanStore((s) => s.lastMessageId);

  useEffect(() => {
    if (!conversationId) { setRecap(null); return; }
    let cancelled = false;
    api.getConversationRecap(conversationId)
      .then((r) => { if (!cancelled) setRecap(r); })
      .catch(() => { if (!cancelled) setRecap(null); });
    return () => { cancelled = true; };
  }, [conversationId]);

  // S3-M3 conversation cumulative usage — on conversation switch and after each
  // turn. Fetch failure → hide the line silently (usage stays null).
  useEffect(() => {
    if (!conversationId) { setUsage(null); return; }
    let cancelled = false;
    api.getConversationUsage(conversationId)
      .then((u) => { if (!cancelled) setUsage(u); })
      .catch(() => { if (!cancelled) setUsage(null); });
    return () => { cancelled = true; };
  }, [conversationId, lastMessageId]);

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
        <span className="recap-dock__title">{t("eval.dock_title")}</span>
        {s && (
          <span className="recap-dock__summary-inline">
            {t("eval.dock_summary", {
              runs: s.run_count,
              avg: s.avg_score ?? "—",
              growth: s.growth_count,
            })}
          </span>
        )}
        <button
          type="button"
          className="recap-dock__link"
          title={t("nav.diagnosis")}
          aria-label={t("nav.diagnosis")}
          onClick={(e) => { e.stopPropagation(); onOpenDiagnosis(); }}
        >
          {/* Icon instead of "Diagnostics ↗": the dock header was crowded, and
              that string was hardcoded English — a Chinese reader saw a label
              nothing could translate. aria-label keeps it reachable. */}
          <HeartPulse className="w-3.5 h-3.5" />
        </button>
      </div>
      {/* S3-M3: conversation cumulative usage — Σ tok · $usd. ≈ = some tokens are
          estimated; trailing + = some tokens carry no USD figure (usd_partial);
          usd_total null = nothing priceable → tokens only (unknown ≠ free). */}
      {usage != null && usage.tokens_total > 0 && (
        <div className="recap-dock__usage" data-testid="conv-usage">
          Σ {usage.estimated_any ? "≈ " : ""}{fmtTok(usage.tokens_total)} tok
          {usage.usd_total != null && ` · ${fmtUsd(usage.usd_total)}${usage.usd_partial ? "+" : ""}`}
        </div>
      )}
      {open && (items.length === 0 ? (
        <div className="recap-dock__empty">{t("eval.dock_empty")}</div>
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
                    {t("eval.run_label")} · {it.overall_score != null ? it.overall_score.toFixed(1) : t("replay.scoring")}
                  </span>
                  <span className="recap-item__title">{it.spawn_name ?? t("diag.spawn")}</span>
                  {it.user_message && <span className="recap-item__sub">{it.user_message}</span>}
                </div>
              ) : (
                <div className="recap-item__body">
                  <span className="recap-item__tag" style={{ color: kindColor(it.kind) }}>
                    {KIND_LABEL_KEY[it.kind] ? t(KIND_LABEL_KEY[it.kind]) : it.kind}
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
