import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { ToolStep } from "../../types";

function StatusIcon({ status }: { status: ToolStep["status"] }) {
  if (status === "running")
    return (
      <span
        className="inline-block h-3 w-3 animate-spin rounded-full border border-white/40 border-t-transparent"
        role="status"
      />
    );
  return <span aria-hidden>{status === "ok" ? "✓" : "✗"}</span>;
}

export default function ToolActivityFrame({ steps, live = false }: { steps: ToolStep[]; live?: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(live);
  if (steps.length === 0) return null;
  const counts: Record<string, number> = {};
  for (const s of steps) counts[s.tool] = (counts[s.tool] ?? 0) + 1;
  const summary = Object.entries(counts)
    .map(([tool, n]) => (n > 1 ? `${tool} ×${n}` : tool))
    .join(", ");
  return (
    <div className="mb-1 max-w-[75%] rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-white/70">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 text-left">
        <span aria-hidden>🛠</span>
        <span>{t("activity.summary", { summary })}</span>
        <span className="ml-auto text-white/40">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {steps.map((s, i) => (
            <li key={i} className="flex flex-col gap-0.5">
              <span className="flex items-center gap-2">
                <StatusIcon status={s.status} />
                <span className="font-medium">{s.tool}</span>
                {s.status === "error" && <span className="text-red-300">{t("activity.error")}</span>}
              </span>
              {s.argsSummary && (
                <span className="pl-5 text-white/40">
                  {t("activity.args")}: {s.argsSummary}
                </span>
              )}
              {s.resultSummary && (
                <span className="pl-5 text-white/50">
                  {t("activity.result")}: {s.resultSummary}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
