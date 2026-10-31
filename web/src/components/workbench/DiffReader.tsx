import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft } from "lucide-react";
import { ApiError } from "../../api/client";
import { filesApi, type ChangeDiff, type ChangeDiffLine } from "../../api/files";
import { baseName, dirName, kindOf } from "../../lib/fileKinds";
import { isolate } from "../CapabilitySwitches";
import FileIcon from "./FileIcon";

/** DIFF1: kinds with no line diff (the server would answer `not_text`), so their rows don't open one. */
const NO_DIFF = new Set(["image", "video", "audio", "pdf", "xlsx", "doc"]);
export const opensDiff = (path: string) => !NO_DIFF.has(kindOf(baseName(path)));

/** Unchanged lines kept on each side of a change; longer unchanged runs fold (as Claude's and GitHub's diffs). */
export const CONTEXT = 3;

type Side = [number, string] | null;
export type SplitRow = { left: Side; right: Side; changed: boolean };

/** The server's lines as two columns: a removed run sits beside the added run after it, line by line; the
 * longer one's rest has an empty other side. A made file is all right-hand rows, a deleted one all left. */
export function sideBySide(lines: ChangeDiffLine[]): SplitRow[] {
  const rows: SplitRow[] = [];
  let i = 0;
  while (i < lines.length) {
    const [op, old, now, text] = lines[i];
    if (op === " ") { rows.push({ left: [old!, text], right: [now!, text], changed: false }); i++; continue; }
    const removed: Side[] = [], added: Side[] = [];
    while (i < lines.length && lines[i][0] === "-") { removed.push([lines[i][1]!, lines[i][3]]); i++; }
    while (i < lines.length && lines[i][0] === "+") { added.push([lines[i][2]!, lines[i][3]]); i++; }
    for (let k = 0; k < Math.max(removed.length, added.length); k++) {
      rows.push({ left: removed[k] ?? null, right: added[k] ?? null, changed: true });
    }
  }
  return rows;
}

/** The rows as shown and folded runs, `from`..`to` (exclusive): an unchanged run longer than the context it
 * leaves folds, keeping CONTEXT rows next to each change. A fold would hide at least two rows; one is shown. */
export function segments(rows: SplitRow[]): { fold: boolean; from: number; to: number }[] {
  const near = rows.map((_, k) => rows.slice(Math.max(0, k - CONTEXT), k + CONTEXT + 1).some((r) => r.changed));
  const keep = near.map((kept, k) => kept || (near[k - 1] !== false && near[k + 1] !== false));
  const out: { fold: boolean; from: number; to: number }[] = [];
  for (let k = 0; k < rows.length; k++) {
    const fold = !keep[k];
    const last = out[out.length - 1];
    if (last && last.fold === fold) last.to = k + 1; else out.push({ fold, from: k, to: k + 1 });
  }
  return out;
}

type Note = "gone" | "hidden" | "failed";
const NOTE_KEY: Record<Note, string> = { gone: "workbench.diffGone", hidden: "workbench.diffHidden", failed: "workbench.diffFailed" };
const cell = "whitespace-pre-wrap px-1.5 align-top [overflow-wrap:anywhere]";
const num = "w-px select-none whitespace-nowrap px-1.5 text-right align-top text-subtle-foreground";

/**
 * DIFF1 (v0.1.64; the user, 2026-10-31: side by side, made and deleted files open too): one path a turn changed,
 * the saved copy (before the turn) on the left and the file now on the right, opened from Overview's Changes.
 * DIFF2: without `runId`, one path of the folder's git repo, its branch's base on the left. Read only; what can't
 * be shown says why in a sentence.
 */
export default function DiffReader({ conversationId, runId, folder, path, onBack }: {
  conversationId: string; runId?: number; folder: string; path: string; onBack: () => void;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<ChangeDiff | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [unfolded, setUnfolded] = useState<number[]>([]);
  useEffect(() => {
    let alive = true;
    const load = runId == null ? filesApi.repoDiff(conversationId, path) : filesApi.changeDiff(conversationId, runId, folder, path);
    load.then((d) => { if (alive) setData(d); }).catch((err) => {
      if (!alive) return;
      const status = err instanceof ApiError ? err.status : 0;
      setNote(status === 404 ? "gone" : status === 403 ? "hidden" : "failed");
    });
    return () => { alive = false; };
  }, [conversationId, runId, folder, path]);
  const rows = useMemo(() => sideBySide(data?.lines ?? []), [data]);
  const parts = useMemo(() => segments(rows), [rows]);
  const name = baseName(path);
  const act = "rounded-md p-1.5 text-muted-foreground hover:bg-foreground/5 hover:text-foreground";

  const line = (r: SplitRow, k: number) => (
    <tr key={k} data-testid={r.changed ? "diff-row-changed" : "diff-row"}>
      <td className={`${num} ${r.left && r.changed ? "bg-danger/10" : ""} ${!r.left ? "bg-fill" : ""}`}>{r.left?.[0] ?? ""}</td>
      <td data-testid="diff-left" className={`${cell} border-r border-border ${!r.left ? "bg-fill" : r.changed ? "bg-danger/10" : ""}`}>
        {r.left?.[1] ?? ""}</td>
      <td className={`${num} ${r.right && r.changed ? "bg-success/10" : ""} ${!r.right ? "bg-fill" : ""}`}>{r.right?.[0] ?? ""}</td>
      <td data-testid="diff-right" className={`${cell} ${!r.right ? "bg-fill" : r.changed ? "bg-success/10" : ""}`}>
        {r.right?.[1] ?? ""}</td>
    </tr>);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="diff-reader">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <button type="button" onClick={onBack} aria-label={t("workbench.back")} className={act} data-testid="diff-back">
          <ChevronLeft size={16} /></button>
        <FileIcon name={name} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold">{isolate(name)}</div>
          <div className="truncate text-[11px] text-subtle-foreground" title={isolate(`${folder}/${path}`)}>
            {isolate(dirName(`${folder}/${path}`))}</div>
        </div>
        {data && !data.reason && <span className="shrink-0 font-mono text-[11.5px]" data-testid="diff-counts">
          <span className="text-success">+{data.added}</span> <span className="text-danger">−{data.removed}</span></span>}
      </div>
      {data?.since && <p className="border-b border-border px-3 py-1.5 text-[11.5px] text-muted-foreground" data-testid="diff-since">
        {t("workbench.diffSince")}</p>}
      {(note || data?.reason) && <p className="px-3 py-3 text-[12.5px] text-muted-foreground" data-testid="diff-note">
        {t(note ? NOTE_KEY[note] : `workbench.diff_${data!.reason}`)}</p>}
      {data && !data.reason && <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full table-fixed border-collapse font-mono text-[11.5px] leading-[1.55]">
          <colgroup><col className="w-10" /><col /><col className="w-10" /><col /></colgroup>
          <tbody>{parts.map((part) => {
            if (!part.fold || unfolded.includes(part.from)) return rows.slice(part.from, part.to).map((r, k) => line(r, part.from + k));
            return <tr key={`f${part.from}`}>
              <td colSpan={4} className="p-0">
                <button type="button" data-testid="diff-fold" onClick={() => setUnfolded([...unfolded, part.from])}
                  className="w-full bg-fill px-3 py-1 text-left font-sans text-[11px] text-muted-foreground hover:text-foreground">
                  ⋯ {t("workbench.diffUnchanged", { count: part.to - part.from })}</button>
              </td>
            </tr>;
          })}</tbody>
        </table>
      </div>}
    </div>
  );
}
