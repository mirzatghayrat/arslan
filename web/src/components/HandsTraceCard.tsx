import { useEffect, useState } from "react";
import { ArrowDownUp, Command, Eye, Keyboard, ListChecks, MousePointerClick, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { request } from "../api/client";
import { formatUiDateTime } from "../lib/localeFormatting";
import ScrollBox from "./activity/ScrollBox";

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
/** 0.1.58 §7: one icon per kind of Hands call; anything that only looks gets the eye. */
export function handsOpIcon(op: string): LucideIcon {
  return ({ click: MousePointerClick, set_value: Keyboard, select: ListChecks, scroll: ArrowDownUp, press: Command } as
    Record<string, LucideIcon>)[op] ?? Eye;
}

/** The trace is one local file read whole (≤ 500 calls); the box shows 20 more each time it reaches its end. */
const STEP = 20;

export default function HandsTraceCard() {
  const { t, i18n } = useTranslation();
  const [entries, setEntries] = useState<HandsTraceEntry[]>([]);
  const [shown, setShown] = useState(STEP);

  useEffect(() => {
    let cancelled = false;
    getHandsTrace().then((r) => { if (!cancelled) setEntries(r.entries ?? []); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  if (entries.length === 0) return null;
  const visible = entries.slice(0, shown);
  return (
    <section data-testid="hands-trace">
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-medium text-foreground">{t("hands.activity.title")}</h2>
        <span className="font-mono text-[11px] text-subtle-foreground">{entries.length}</span>
      </div>
      <div className="mt-3">
        <ScrollBox scrollKey="hands" testId="hands-box" onEnd={() => setShown((n) => Math.min(entries.length, n + STEP))}>
          <ul className="divide-y divide-border">
            {visible.map((e, i) => {
              const Icon = handsOpIcon(e.op);
              return (
                <li key={`${e.at}-${i}`} className="flex items-center gap-3 px-3 py-2 text-[12px]" data-testid="hands-row">
                  <Icon size={14} aria-hidden data-op={e.op} className="shrink-0 text-muted-foreground" />
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
              );
            })}
          </ul>
        </ScrollBox>
      </div>
    </section>
  );
}
