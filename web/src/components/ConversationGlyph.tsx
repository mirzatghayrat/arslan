import { Check, Clock, MessageSquare, RadioTower, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ConversationMeta } from "../lib/conversationMeta";

/** One glyph per conversation: what it is and how it stands, the same language as the iPhone's
 *  task list — a progress ring while a task runs, amber "!" when it waits for you, green check when
 *  done, red cross when it failed, a clock for scheduled work, a signal tower for Remote. */
export default function ConversationGlyph({ meta, size = 15 }: { meta?: ConversationMeta; size?: number }) {
  const { t } = useTranslation();
  const label = (key: string) => t(`sidebar.glyph.${key}`);
  if (!meta || (meta.kind === "chat" && meta.state === "idle")) {
    return <MessageSquare size={size - 1} className="shrink-0" aria-hidden />;
  }
  if (meta.state === "waiting") {
    return <span role="img" aria-label={label("waiting")} title={label("waiting")}
      className="flex shrink-0 items-center justify-center rounded-full border-2 border-warning text-[9px] font-extrabold leading-none text-warning"
      style={{ width: size, height: size }}>!</span>;
  }
  if (meta.kind === "remote") {
    return <RadioTower size={size} className="shrink-0 text-foreground" role="img" aria-label={label("remote")} />;
  }
  if (meta.state === "working") {
    const r = 6, c = 2 * Math.PI * r;
    const fraction = meta.job && meta.job.total > 0 ? Math.max(0.12, meta.job.done / meta.job.total) : 0.3;
    return <svg role="img" aria-label={meta.job ? t("sidebar.glyph.progress", { done: meta.job.done, total: meta.job.total }) : label("working")}
      width={size} height={size} viewBox="0 0 16 16" className="shrink-0">
      <circle cx="8" cy="8" r={r} fill="none" strokeWidth="2.2" className="stroke-foreground/15" />
      <circle cx="8" cy="8" r={r} fill="none" strokeWidth="2.2" strokeLinecap="round" className="stroke-primary"
        strokeDasharray={`${(c * fraction).toFixed(1)} ${c.toFixed(1)}`} transform="rotate(-90 8 8)" />
    </svg>;
  }
  if (meta.state === "done") return <Check size={size} strokeWidth={2.4} className="shrink-0 text-success" role="img" aria-label={label("done")} />;
  if (meta.state === "failed") return <X size={size - 1} strokeWidth={2.4} className="shrink-0 text-danger" role="img" aria-label={label("failed")} />;
  if (meta.kind === "scheduled") return <Clock size={size} className="shrink-0" role="img" aria-label={label("scheduled")} />;
  return <MessageSquare size={size - 1} className="shrink-0" aria-hidden />;
}
