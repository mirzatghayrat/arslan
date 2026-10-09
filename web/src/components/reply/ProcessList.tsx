import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, ChevronRight, X } from "lucide-react";
import { api } from "../../api/client";
import type { RunProcessOut } from "../../api/client.types";
import MarkdownLink from "../MarkdownLink";
import MatrixSpinner from "../MatrixSpinner";
import { fmtDuration, group, stepWords, type ProcessEntry, type ProcessItem, type StepDetail } from "../../lib/process";

/** One fetch per run per window: a finished reply's steps do not change. */
const cache = new Map<number, Promise<RunProcessOut>>();
export function fetchProcess(runId: number): Promise<RunProcessOut> {
  let p = cache.get(runId);
  if (!p) {
    p = api.runProcess(runId);
    cache.set(runId, p);
    p.catch(() => cache.delete(runId));
  }
  return p;
}
export function _resetProcessCache() { cache.clear(); }

export function toEntries(out: RunProcessOut): ProcessEntry[] {
  return out.entries.map((e) => e.kind === "note"
    ? { kind: "note", text: e.text ?? "", status: "ok" }
    : { kind: "tool", tool: e.tool, status: e.ok ? "ok" : "error", ms: e.ms ?? null, argsSummary: e.args_summary,
        summary: e.summary, detail: e.detail, raw: e.raw });
}

const mono = "font-mono text-[11px] leading-relaxed";

function Lines({ head }: { head?: unknown }) {
  const { t } = useTranslation();
  const h = head as { lines?: string[]; more?: number } | undefined;
  if (!h?.lines?.length) return null;
  return (
    <div className={`${mono} rounded-md border border-border/60 bg-background px-2.5 py-1.5 text-muted-foreground`}>
      {h.lines.map((line, i) => <div key={i} className="whitespace-pre-wrap break-all">{line}</div>)}
      {!!h.more && <div className="text-subtle-foreground">{t("process.moreLines", { count: h.more })}</div>}
    </div>
  );
}

/** The few things worth seeing for one step — never its JSON (0.1.58 §1, decision 2). */
export function StepDetailView({ detail, raw }: { detail?: StepDetail; raw?: ProcessEntry["raw"] }) {
  const { t } = useTranslation();
  if (!detail) return null;
  const d = detail as Record<string, unknown> & StepDetail;
  const rows: React.ReactNode[] = [];
  const text = (v: unknown) => (typeof v === "string" ? v : "");
  switch (d.view) {
    case "search":
      rows.push(<div key="q" className="text-muted-foreground">{text(d.query)}{typeof d.count === "number"
        ? ` · ${t("process.results", { count: d.count })}` : ""}{d.provider ? ` · ${t("process.via", { provider: d.provider })}` : ""}</div>);
      for (const link of (d.links as { title: string; url: string }[] | undefined) ?? []) {
        rows.push(<div key={link.url} className="truncate"><MarkdownLink href={link.url}>{link.title || link.url}</MarkdownLink></div>);
      }
      break;
    case "page":
      rows.push(<div key="u" className="truncate"><MarkdownLink href={text(d.url)}>{text(d.title) || text(d.url)}</MarkdownLink></div>);
      if (typeof d.chars === "number" && d.chars > 0) rows.push(<div key="c" className="text-muted-foreground">{t("process.chars", { count: d.chars })}</div>);
      break;
    case "file":
    case "write":
    case "find":
      rows.push(<div key="p" className={`${mono} text-foreground`}>{text(d.path) || text(d.query)}</div>);
      if (typeof d.entries === "number") rows.push(<div key="e" className="text-muted-foreground">{t("process.entries", { count: d.entries })}</div>);
      if (typeof d.chars === "number") rows.push(<div key="c" className="text-muted-foreground">{t("process.chars", { count: d.chars })}</div>);
      if (typeof d.bytes === "number") rows.push(<div key="b" className="text-muted-foreground">{t("process.bytes", { count: d.bytes })}</div>);
      if (typeof d.count === "number") rows.push(<div key="n" className="text-muted-foreground">{t("process.results", { count: d.count })}</div>);
      break;
    case "edit":
      rows.push(<div key="p" className={`${mono} text-foreground`}>{text(d.path)}</div>);
      rows.push(<div key="o" className={`${mono} rounded-md bg-danger/5 px-2 py-1 text-muted-foreground whitespace-pre-wrap break-all`}>
        <span className="text-subtle-foreground">{t("process.oldText")} </span>{text(d.old)}</div>);
      rows.push(<div key="n" className={`${mono} rounded-md bg-success/5 px-2 py-1 text-foreground whitespace-pre-wrap break-all`}>
        <span className="text-subtle-foreground">{t("process.newText")} </span>{text(d.new)}</div>);
      break;
    case "command":
      rows.push(<div key="c" className={`${mono} rounded-md bg-foreground px-2.5 py-1.5 text-background whitespace-pre-wrap break-all`}>{text(d.command)}</div>);
      if (d.exit_code != null) rows.push(<div key="x" className="text-muted-foreground">{t("process.exit", { code: d.exit_code })}</div>);
      rows.push(<Lines key="h" head={d.head} />);
      break;
    case "code":
      rows.push(<Lines key="h" head={d.head} />);
      if (Array.isArray(d.files) && d.files.length) rows.push(<div key="f" className="text-muted-foreground">{t("process.made")}: {(d.files as string[]).join(", ")}</div>);
      break;
    case "release":
      if (d.version) rows.push(<div key="v" className="text-muted-foreground">{t("process.release", { version: d.version })}</div>);
      break;
    case "recall":
      rows.push(<div key="q" className="text-muted-foreground">{text(d.query)}{typeof d.count === "number" ? ` · ${t("process.results", { count: d.count })}` : ""}</div>);
      break;
    default: {
      const args = (d.args as [string, string][] | undefined) ?? [];
      if (args.length) rows.push(<div key="a" className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11.5px]">
        {args.map(([k, v]) => [<span key={`k${k}`} className="text-subtle-foreground">{k}</span>,
          <span key={`v${k}`} className="min-w-0 break-all text-foreground">{v}</span>])}</div>);
      rows.push(<Lines key="h" head={d.head} />);
    }
  }
  if (d.error) rows.push(<div key="err" className="text-danger">{t("process.error", { error: d.error })}</div>);
  return (
    <div className="mt-1 ml-6 flex flex-col gap-1 text-[12px]" data-testid="step-detail" data-view={d.view}>
      {rows}
      {raw && <details className="text-[11px]" data-testid="step-raw">
        <summary className="cursor-pointer text-subtle-foreground">{t("process.raw")}</summary>
        <div className="mt-1 text-subtle-foreground">{t("process.rawArgs")}</div>
        <pre className={`${mono} whitespace-pre-wrap break-all rounded-md bg-background p-2 text-muted-foreground`}>{raw.args}</pre>
        <div className="mt-1 text-subtle-foreground">{t("process.rawResult")}</div>
        <pre className={`${mono} whitespace-pre-wrap break-all rounded-md bg-background p-2 text-muted-foreground`}>{raw.result}</pre>
      </details>}
    </div>
  );
}

function Mark({ status }: { status: ProcessEntry["status"] }) {
  return status === "running" ? <MatrixSpinner size={12} className="shrink-0 text-primary" />
    : status === "error" ? <X className="h-3 w-3 shrink-0 text-danger" aria-hidden />
    : <Check className="h-3 w-3 shrink-0 text-success" aria-hidden />;
}

/** One step line; finished ones open to their detail. */
export function StepLine({ entry, open, onToggle }: { entry: ProcessEntry; open?: boolean; onToggle?: () => void }) {
  const { t } = useTranslation();
  const canOpen = !!entry.detail && !!onToggle;
  return (
    <div data-testid="process-step" data-tool={entry.tool}>
      <button type="button" disabled={!canOpen} onClick={onToggle} aria-expanded={canOpen ? !!open : undefined}
        className="flex w-full min-w-0 items-center gap-2 text-left text-[12px] disabled:cursor-default">
        <Mark status={entry.status} />
        <span className={`min-w-0 flex-1 truncate ${entry.status === "error" ? "text-muted-foreground" : "text-foreground"}`}>
          {stepWords(entry, t)}</span>
        {entry.ms != null && entry.status !== "running" && <span className="shrink-0 font-mono text-[10.5px] text-subtle-foreground">{fmtDuration(entry.ms)}</span>}
        {canOpen && (open ? <ChevronDown className="h-3 w-3 shrink-0 text-subtle-foreground" /> : <ChevronRight className="h-3 w-3 shrink-0 text-subtle-foreground" />)}
      </button>
      {open && <StepDetailView detail={entry.detail} raw={entry.raw} />}
    </div>
  );
}

function GroupLine({ item }: { item: Extract<ProcessItem, { kind: "group" }> }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [openStep, setOpenStep] = useState<number | null>(null);
  const failed = item.entries.some((e) => e.status === "error");
  return (
    <div data-testid="process-group" data-family={item.family}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="flex w-full items-center gap-2 text-left text-[12px]">
        <Mark status={failed ? "error" : "ok"} />
        <span className="min-w-0 flex-1 truncate">{t(`process.group_${item.family}`, { count: item.entries.length })}</span>
        {open ? <ChevronDown className="h-3 w-3 text-subtle-foreground" /> : <ChevronRight className="h-3 w-3 text-subtle-foreground" />}
      </button>
      {open && <div className="ml-5 mt-1 flex flex-col gap-1">
        {item.entries.map((e, i) => <StepLine key={i} entry={e} open={openStep === i} onToggle={() => setOpenStep(openStep === i ? null : i)} />)}
      </div>}
    </div>
  );
}

/**
 * The opened list under a reply's footer row: narration and steps in order, reads and
 * searches folded together, each step opening to plain details. A recorded reply always
 * reads its run (the same list after a reload); the in-memory steps show meanwhile.
 */
export default function ProcessList({ runId, live, onReplay }: {
  runId?: number | null; live: ProcessEntry[]; onReplay?: (runId: number) => void;
}) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<ProcessEntry[] | null>(runId ? null : live);
  const [openStep, setOpenStep] = useState<number | null>(null);
  useEffect(() => {
    if (!runId) { setEntries(live); return; }
    let alive = true;
    fetchProcess(runId).then((out) => { if (alive) setEntries(toEntries(out)); })
      .catch(() => { if (alive) setEntries(live); });
    return () => { alive = false; };
  }, [runId, live]);
  const shown = entries ?? live;
  const items = group(shown);
  return (
    <div className="ml-5 mt-1.5 flex max-w-xl flex-col gap-1.5 rounded-xl bg-foreground/[0.025] px-3 py-2.5" data-testid="process-list">
      {entries == null && !live.length && <span className="text-[11.5px] text-subtle-foreground">{t("process.loading")}</span>}
      {items.map((item, i) => item.kind === "note"
        ? <p key={i} className="text-[12px] leading-relaxed text-muted-foreground" data-testid="process-note">{item.text}</p>
        : item.kind === "group" ? <GroupLine key={i} item={item} />
        : <StepLine key={i} entry={item} open={openStep === i} onToggle={() => setOpenStep(openStep === i ? null : i)} />)}
      {runId && onReplay && <button type="button" onClick={() => onReplay(runId)} data-testid="process-replay"
        className="self-start text-[11.5px] text-subtle-foreground hover:text-foreground">{t("process.viewProcess")} ›</button>}
    </div>
  );
}
