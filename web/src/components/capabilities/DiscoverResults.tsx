import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { CapabilityCandidate, CapabilitySearch } from "../../api/capabilities";
import { Button, Tag } from "../kit";

type Filter = "all" | CapabilityCandidate["kind"];
const FILTERS: Filter[] = ["all", "skill", "mcp", "project"];

const host = (url: string | undefined | null) => {
  try { return url ? new URL(url).host : ""; } catch { return url ?? ""; }
};

/** The one line that says how it would run here — or why it cannot (0.1.57 §2). */
export function runLine(t: (k: string, o?: Record<string, unknown>) => string, c: CapabilityCandidate): string {
  if (c.license.verdict === "reference_only") return t("discover.ref_only");
  if (c.license.verdict === "unknown" && c.kind !== "project") return t("discover.unknown_only");
  if (c.not_here) return t(`discover.nh_${c.not_here}`);
  if (c.kind === "project") return t("discover.run_project");
  if (c.runtime === "remote") return t("discover.run_remote", { host: host(c.remote?.url) });
  return c.runtime ? t(`discover.run_${c.runtime}`) : "";
}

function LicenseTag({ c }: { c: CapabilityCandidate }) {
  const { t } = useTranslation();
  const v = c.license.verdict;
  return <span title={c.license.read_from ? t("discover.lic_readFrom") : undefined} data-testid={`cand-license-${c.id}`}
    className={`whitespace-nowrap rounded-full px-[7px] py-0.5 text-[11px] ${v === "usable" ? "bg-success/10 text-success"
      : v === "reference_only" ? "bg-danger-soft text-danger-strong" : "bg-fill text-muted-foreground"}`}>
    {v === "usable" ? t("discover.lic_usable", { spdx: c.license.spdx }) : t(v === "reference_only" ? "discover.lic_reference" : "discover.lic_unknown")}
  </span>;
}

/**
 * The Discover box's results (board Capabilities-v3): by what you want done, across the official
 * MCP Registry, GitHub and skill libraries; each with its license (read at the source), activity,
 * and how it would run here. Looking and saving only — installing is a card in a conversation.
 */
export default function DiscoverResults({ result, busyId, onLook, onSave }: {
  result: CapabilitySearch; busyId?: string | null;
  onLook: (c: CapabilityCandidate) => void; onSave: (c: CapabilityCandidate) => void;
}) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<Filter>("all");
  const count = (f: Filter) => f === "all" ? result.candidates.length : result.candidates.filter(c => c.kind === f).length;
  const shown = result.candidates.filter(c => filter === "all" || c.kind === filter);
  return (
    <section className="mx-auto mt-6 flex max-w-3xl flex-col gap-2.5 text-left" data-testid="discover-results">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg bg-fill p-0.5" role="group">
          {FILTERS.map(f => <button key={f} type="button" aria-pressed={filter === f} data-testid={`discover-filter-${f}`}
            onClick={() => setFilter(f)} className={`rounded-md px-2.5 py-1 text-[12px] ${filter === f
              ? "bg-background font-semibold shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
            {t(f === "all" ? "discover.all" : `discover.kind_${f}`)} <span className="font-mono text-[11px] opacity-60">{count(f)}</span>
          </button>)}
        </div>
        <span className="ml-auto text-[11.5px] text-subtle-foreground">{t("discover.sources")}</span>
      </div>
      {result.words.length > 0 && <p className="text-[11.5px] text-subtle-foreground" data-testid="discover-words">
        {t("discover.searchedFor", { words: result.words.join(", ") })}</p>}
      {result.notes.map(n => <p key={n} className="text-[12px] text-muted-foreground" data-testid={`discover-note-${n}`}>
        {t(`discover.note_${n}`)}</p>)}
      {!shown.length && !result.notes.includes("no_keywords") && <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-[13px] text-muted-foreground">
        {t("discover.none")}</p>}
      {shown.map(c => (
        <article key={c.id} data-testid={`cand-${c.id}`} className="flex flex-col gap-1.5 rounded-xl border border-border bg-background px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <Tag>{t(`discover.kind_${c.kind}`)}</Tag>
            <span className="text-[14px] font-semibold">{c.name}</span>
            <LicenseTag c={c} />
            {c.stars != null && <span className="text-[11.5px] text-subtle-foreground">{t("discover.stars", { stars: c.stars })}</span>}
            {c.pushed_days != null && <span className="text-[11.5px] text-subtle-foreground">{t("discover.pushed", { count: c.pushed_days })}</span>}
            {c.source_url && <a href={c.source_url} target="_blank" rel="noopener noreferrer" aria-label={t("discover.open")}
              className="ml-auto text-subtle-foreground hover:text-foreground"><ArrowUpRight size={14} /></a>}
          </div>
          {c.summary && <p className="text-[13px] leading-snug">{c.summary}</p>}
          <p className="text-[12px] text-muted-foreground" data-testid={`cand-run-${c.id}`}>{runLine(t, c)}</p>
          {c.needs.keys.some(k => k.required) && <p className="text-[12px] text-muted-foreground">
            {t("discover.needsKeys", { keys: c.needs.keys.filter(k => k.required).map(k => k.name).join(", ") })}</p>}
          {c.repo && <div className="flex gap-1.5">
            <Button size="sm" disabled={busyId === c.id} onClick={() => onLook(c)} data-testid={`cand-look-${c.id}`}>{t("discover.look")}</Button>
            <Button size="sm" disabled={busyId === c.id} onClick={() => onSave(c)} data-testid={`cand-save-${c.id}`}>{t("discover.save")}</Button>
          </div>}
        </article>
      ))}
    </section>
  );
}
