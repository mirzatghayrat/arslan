import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Board, BoardCard } from "../../api/projects";
import ShadowStrip from "./ShadowStrip";
import { Button } from "../kit";
import ProjectCard, { LevelBar } from "./ProjectCard";
import { BAND_DOT, BOARD_COLUMNS } from "./projectUi";

type View = "board" | "list";

/**
 * Layer 1 (0.1.56 §1): four columns for every project. Where a card sits follows the level
 * it is on; Done and Dropped are only the user's. No drag and drop: Arslan says "this can
 * move" on the card, the user agrees.
 */
export default function ProjectsBoard({ board, onOpen, onNew, onPlan, onDecide, onResume, onPause, onAuto, onNote, onHabits, busy }: {
  board: Board; onOpen: (id: string) => void; onNew: () => void; onPlan: (id: string) => void;
  onDecide: (card: BoardCard, accept: boolean) => void; busy?: boolean;
  onResume?: (card: BoardCard) => void; onPause?: (card: BoardCard) => void;
  onAuto?: (on: boolean, answered: "ask" | "offer") => void; onNote?: (note: string) => void; onHabits?: () => void;
}) {
  const { t } = useTranslation();
  const [view, setView] = useState<View>("board");
  const [showDropped, setShowDropped] = useState(false);
  const dropped = board.cards.filter(c => c.column === "dropped");
  const card = (c: BoardCard) => <ProjectCard key={c.id} card={c} busy={busy} onOpen={() => onOpen(c.id)}
    onPlan={() => onPlan(c.id)} onDecide={(accept) => onDecide(c, accept)}
    onResume={onResume && (() => onResume(c))} onPause={onPause && (() => onPause(c))} />;
  const s = board.shadow;
  return (
    <section className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto px-5 py-5 sm:px-8" aria-label={t("projectsUI.title")}>
      <header className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-[20px] font-bold leading-tight">{t("projectsUI.title")}</h1>
          <p className="mt-0.5 max-w-3xl text-[12.5px] text-muted-foreground">{t("projectsUI.intro")}</p>
        </div>
        <span className="self-center text-[12px] text-muted-foreground" data-testid="projects-counts">
          {t("projectsUI.paused", { count: board.counts.paused })} · {t("projectsUI.archived", { count: board.counts.archived })}</span>
        <div className="inline-flex self-center rounded-lg bg-fill p-0.5" role="group">
          {(["board", "list"] as const).map(v => <button key={v} type="button" aria-pressed={view === v} data-testid={`projects-view-${v}`}
            onClick={() => setView(v)} className={`rounded-md px-3 py-1 text-[12.5px] ${view === v
              ? "bg-background font-semibold shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
            {t(v === "board" ? "projectsUI.viewBoard" : "projectsUI.viewList")}</button>)}
        </div>
        <Button size="sm" tone="primary" onClick={onNew} data-testid="projects-new"><Plus size={13} />{t("projectsUI.newProject")}</Button>
      </header>

      {!board.cards.length && <p className="rounded-xl border border-dashed border-border p-12 text-center text-[13px] text-muted-foreground">
        {t("projectsUI.empty")}</p>}

      {board.cards.length > 0 && view === "board" && (
        <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-4">
          {BOARD_COLUMNS.map(col => {
            const cards = board.cards.filter(c => c.column === col);
            return (
              <div key={col} data-testid={`projects-col-${col}`} className="flex min-w-0 flex-col gap-2.5 rounded-2xl bg-fill/60 p-2.5">
                <div className="flex items-center gap-2 px-1">
                  <span aria-hidden="true" className={`h-2 w-2 rounded-full ${BAND_DOT[col === "idea" ? "idea" : col]}`} />
                  <span className="text-[13px] font-bold">{t(`projectsUI.col_${col}`)}</span>
                  <span className="font-mono text-[12px] text-subtle-foreground">{cards.length}</span>
                </div>
                {col !== "done" && <span className="-mt-1.5 px-1 text-[11px] text-subtle-foreground">{t(`projectsUI.col_${col}_sub`)}</span>}
                {cards.map(card)}
                {col === "done" && dropped.length > 0 && (
                  <button type="button" className="px-1 text-left text-[12px] text-muted-foreground hover:text-foreground"
                    aria-expanded={showDropped} onClick={() => setShowDropped(v => !v)} data-testid="projects-dropped-toggle">
                    {t("projectsUI.col_dropped", { count: dropped.length })}</button>)}
                {col === "done" && showDropped && dropped.map(card)}
              </div>
            );
          })}
        </div>
      )}

      {board.cards.length > 0 && view === "list" && (
        <table className="w-full border-separate border-spacing-0 overflow-hidden rounded-xl border border-border text-[13px]" data-testid="projects-list">
          <thead><tr className="text-left text-[12px] text-muted-foreground">
            {["listName", "listColumn", "listLevel", "listLeft"].map(k => <th key={k} className="border-b border-border px-3 py-2 font-medium">{t(`projectsUI.${k}`)}</th>)}
          </tr></thead>
          <tbody>{board.cards.map(c => (
            <tr key={c.id} className="cursor-pointer hover:bg-fill" onClick={() => onOpen(c.id)}>
              <td className="border-b border-border px-3 py-2 font-medium">{c.name}</td>
              <td className="border-b border-border px-3 py-2">{t(c.column === "dropped" ? "projectsUI.droppedName" : `projectsUI.col_${c.column}`)}</td>
              <td className="border-b border-border px-3 py-2"><div className="flex flex-col gap-1">
                {c.current ? `${t("projectsUI.level", { n: c.current.position })} · ${c.current.name}` : "—"}
                {c.has_plan && <LevelBar levels={c.levels} />}</div></td>
              <td className="border-b border-border px-3 py-2 font-mono">{c.has_plan ? c.left : "—"}</td>
            </tr>))}</tbody>
        </table>
      )}

      {board.cards.length > 0 && <ShadowStrip shadow={s} busy={busy} onAuto={(on, answered) => onAuto?.(on, answered)}
        onNote={note => onNote?.(note)} onHabits={() => onHabits?.()} />}
    </section>
  );
}
