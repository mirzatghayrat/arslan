import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, MoreHorizontal } from "lucide-react";
import type { ProcessSummary } from "../../api/client.types";
import { useDismissable } from "../../hooks/useDismissable";
import { fmtTok, fmtUsd } from "../../lib/usageFormat";
import { fmtDuration, type ProcessEntry } from "../../lib/process";
import CopyButton from "../CopyButton";
import { buildStandaloneHtml, exportMarkdown, triggerDownload } from "../MessageBody";
import ProcessList from "./ProcessList";

/** 0.1.58 §1: opens Activity with this turn in its drawer (App listens). */
export const OPEN_ACTIVITY_RUN_EVENT = "arslan:open-activity-run";

export interface ReplyProcess {
  runId: number | null;
  entries: ProcessEntry[];
  summary: ProcessSummary;
}

/** Open upwards unless the anchor is too close to the top of the window to fit. */
const ROOM = 260;
const upward = (el: HTMLElement | null) => !el || el.getBoundingClientRect().top > ROOM;

const iconBtn = "rounded-md p-1 text-subtle-foreground hover:bg-foreground/5 hover:text-foreground focus:opacity-100";

/** The model name; a click shows what the turn used (0.1.58 §1, decision 3: tokens leave the reply row). */
function ModelUsage({ summary }: { summary: ProcessSummary }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [up, setUp] = useState(true);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(open, () => setOpen(false));
  const usage = summary.usage;
  const models = usage?.models?.map((m) => m.model).filter(Boolean) ?? [];
  if (!models.length) return null;
  const est = usage?.estimated ? "≈ " : "";
  const row = (label: string, value: string) => (
    <div className="flex justify-between gap-6"><span className="text-muted-foreground">{label}</span>
      <span className="font-mono tabular-nums">{value}</span></div>
  );
  return (
    <span className="relative">
      <button ref={anchorRef} type="button" onClick={() => { setUp(upward(anchorRef.current)); setOpen((v) => !v); }}
        aria-expanded={open} aria-haspopup="dialog"
        title={t("process.model")} data-testid="reply-model"
        className="inline-flex max-w-[220px] items-center gap-0.5 truncate whitespace-nowrap rounded-md px-1 py-0.5 font-mono text-[11px] text-subtle-foreground hover:text-foreground">
        {models.join(" + ")}<ChevronDown className="h-3 w-3" />
      </button>
      {open && <div ref={floatingRef} role="dialog" data-testid="reply-usage"
        className={`absolute right-0 z-30 w-72 rounded-xl border border-border bg-background p-3 text-[12px] shadow-lg ${up ? "bottom-full mb-1.5" : "top-full mt-1.5"}`}>
        <div className="mb-1.5 font-semibold">{models.join(" + ")}</div>
        <div className="flex flex-col gap-1">
          {usage?.calls != null && row(t("process.calls"), t("process.callsN", { count: usage.calls }))}
          {usage?.tokens_in != null && row(t("process.input"), `${est}${fmtTok(usage.tokens_in)}`)}
          {usage?.tokens_out != null && row(t("process.output"), `${est}${fmtTok(usage.tokens_out)}`)}
          {usage?.tokens_in == null && usage?.tokens_total != null && row(t("process.input"), `${est}${fmtTok(usage.tokens_total)}`)}
          {row(t("process.cost"), usage?.usd != null ? `≈ ${fmtUsd(usage.usd)}` : t("process.unknown"))}
          {summary.ms != null && row(t("process.time"), fmtDuration(summary.ms))}
        </div>
        <p className="mt-2 border-t border-border pt-2 text-[11.5px] leading-snug text-subtle-foreground">{t("process.inputWhy")}</p>
      </div>}
    </span>
  );
}

/**
 * The one row under an Arslan reply (0.1.58 §1, decision 1): what it did ("✓ 6 步 · 48 秒",
 * opening the steps below), which model, copy, and ⋯ — in the place the "…" was, nothing
 * above the answer. The latest reply shows it all; earlier ones show copy and ⋯ on hover.
 */
export default function ReplyFooter({ text, process, latest, onReplay }: {
  text: string; process: ReplyProcess; latest: boolean; onReplay?: (runId: number) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [menuUp, setMenuUp] = useState(true);
  const rowRef = useRef<HTMLDivElement>(null);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(menu, () => setMenu(false));
  const { summary, runId } = process;
  const quiet = latest ? "" : "opacity-0 group-hover/reply:opacity-100 focus-within:opacity-100";
  const downloadHtml = () => {
    const root = rowRef.current?.closest("[data-reply]")?.querySelector("[data-md-root]");
    triggerDownload(`message-${Date.now()}.html`, buildStandaloneHtml(root?.innerHTML ?? "", "Arslan export"), "text/html;charset=utf-8");
  };
  const item = "block w-full rounded px-2 py-1.5 text-left text-[12px] hover:bg-foreground/5";
  return (
    <div className="pl-5" data-testid="reply-footer">
      <div ref={rowRef} className="flex min-h-[26px] items-center gap-2">
        {summary.steps > 0 && (
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} data-testid="reply-steps"
            className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-foreground/[0.05] px-2.5 py-0.5 text-[11.5px] text-muted-foreground hover:bg-foreground/[0.08]">
            <span className={summary.failed ? "text-warning" : "text-success"}>{summary.failed ? "⚠" : "✓"}</span>
            {t("process.steps", { count: summary.steps })}
            {summary.failed > 0 && ` · ${t("process.failed", { count: summary.failed })}`}
            {summary.ms != null && ` · ${fmtDuration(summary.ms)}`}
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
        )}
        <span className="flex-1" />
        <ModelUsage summary={summary} />
        <span className={`flex items-center gap-0.5 transition-opacity ${quiet}`}>
          <CopyButton text={text} className={iconBtn} />
          <span className="relative">
            <button ref={anchorRef} type="button" aria-label={t("process.more")} aria-haspopup="menu" aria-expanded={menu}
              onClick={() => { setMenuUp(upward(anchorRef.current)); setMenu((v) => !v); }} className={iconBtn} data-testid="reply-more">
              <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
            </button>
            {menu && <div ref={floatingRef} role="menu"
              className={`absolute right-0 z-30 min-w-44 rounded-md border border-border bg-background p-1 shadow-md ${menuUp ? "bottom-full mb-1" : "top-full mt-1"}`}>
              {runId && onReplay && <button type="button" role="menuitem" className={item} data-testid="reply-replay"
                onClick={() => { setMenu(false); onReplay(runId); }}>{t("process.viewProcess")}</button>}
              {runId && <button type="button" role="menuitem" className={item}
                onClick={() => { setMenu(false); window.dispatchEvent(new CustomEvent(OPEN_ACTIVITY_RUN_EVENT, { detail: runId })); }}>
                {t("process.openActivity")}</button>}
              <button type="button" role="menuitem" className={item} data-testid="reply-download-md"
                onClick={() => { setMenu(false); triggerDownload(`message-${Date.now()}.md`, exportMarkdown(text), "text/markdown;charset=utf-8"); }}>
                {t("process.downloadMd")}</button>
              <button type="button" role="menuitem" className={item} onClick={() => { setMenu(false); downloadHtml(); }}>
                {t("process.downloadHtml")}</button>
            </div>}
          </span>
        </span>
      </div>
      {open && <ProcessList runId={runId} live={process.entries} onReplay={onReplay} />}
    </div>
  );
}
