import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { request } from "../api/client";
import { formatUiDateTime } from "../lib/localeFormatting";

/** One Hands call as the backend traced it (0.1.53): never typed text, only its length. */
export interface HandsTraceEntry {
  at: string;
  app?: string | null;
  op: string;
  outcome: string;
  target?: string | null;
  typed_chars?: number;
  ms?: number;
}

export const getHandsTrace = () => request<{ entries: HandsTraceEntry[] }>("/hands/trace?days=7&limit=100");

/**
 * Arslan Hands in Activity (0.1.53): every look and action in Mac apps from the
 * last 7 days (the trace file is 0600 and pruned after 7 days). Shown only when
 * there is something to show.
 */
export default function HandsTraceCard() {
  const { t, i18n } = useTranslation();
  const [entries, setEntries] = useState<HandsTraceEntry[]>([]);

  useEffect(() => {
    let cancelled = false;
    getHandsTrace().then((r) => { if (!cancelled) setEntries(r.entries ?? []); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  if (entries.length === 0) return null;
  return (
    <section data-testid="hands-trace">
      <h2 className="text-sm font-medium text-foreground">{t("hands.activity.title")}</h2>
      <ul className="mt-3 divide-y divide-border rounded-lg border border-border bg-surface/40">
        {entries.map((e, i) => (
          <li key={`${e.at}-${i}`} className="flex items-center gap-3 px-3 py-2 text-[12px]">
            <span className="shrink-0 w-24 truncate text-foreground">{e.app ?? "—"}</span>
            <span className="shrink-0 w-20 font-mono text-[11px] text-muted-foreground">{e.op}</span>
            <span className="min-w-0 flex-1 truncate text-muted-foreground">
              {e.target ?? ""}{e.typed_chars != null ? ` (${e.typed_chars})` : ""}
            </span>
            <span className={`shrink-0 w-28 text-right font-mono text-[11px] ${e.outcome === "ok" ? "text-subtle-foreground" : "text-destructive"}`}>
              {e.outcome}
            </span>
            <span className="shrink-0 w-32 text-right font-mono text-[11px] text-subtle-foreground">
              {formatUiDateTime(e.at, i18n.language)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
