import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Shadow } from "../../api/projects";
import { Button } from "../kit";

const SKIP_KEY = "arslan.projects.missNoteSkipped";

/**
 * Under the board (0.1.56 §5): how well Arslan guesses when a level is cleared, the one ask
 * at ten in a row, the offer to stop after two undos in a row, and the optional line after a
 * decline. Everything here waits on the board — nothing is a notification.
 */
export default function ShadowStrip({ shadow, busy, onAuto, onNote, onHabits }: {
  shadow: Shadow; busy?: boolean;
  onAuto: (on: boolean, answered: "ask" | "offer") => void;
  onNote: (note: string) => void;
  onHabits: () => void;
}) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const [skipped, setSkipped] = useState<string | null>(() => {
    try { return localStorage.getItem(SKIP_KEY); } catch { return null; }
  });
  const skip = (missId: string) => {
    setSkipped(missId);
    try { localStorage.setItem(SKIP_KEY, missId); } catch { /* the box just comes back next time */ }
  };
  const miss = shadow.last_miss;
  const askNote = miss && shadow.miss_is_latest && miss.outcome === "declined" && !miss.note && skipped !== miss.id;
  return (
    <div className="flex flex-col gap-2">
      {shadow.ask_due && (
        <div data-testid="projects-auto-ask" className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-background px-3.5 py-2.5">
          <span className="min-w-0 flex-1 text-[13px]">{t("projectsUI.autoAsk", { count: shadow.streak })}</span>
          <Button size="sm" tone="primary" disabled={busy} onClick={() => onAuto(true, "ask")} data-testid="projects-auto-yes">
            {t("projectsUI.autoYes")}</Button>
          <Button size="sm" disabled={busy} onClick={() => onAuto(false, "ask")} data-testid="projects-auto-no">
            {t("projectsUI.autoNo")}</Button>
        </div>
      )}
      {shadow.offer_off && (
        <div data-testid="projects-auto-offer" className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-background px-3.5 py-2.5">
          <span className="min-w-0 flex-1 text-[13px]">{t("projectsUI.autoOffer")}</span>
          <Button size="sm" tone="primary" disabled={busy} onClick={() => onAuto(false, "offer")} data-testid="projects-auto-off">
            {t("projectsUI.autoTurnOff")}</Button>
          <Button size="sm" disabled={busy} onClick={() => onAuto(true, "offer")} data-testid="projects-auto-keep">
            {t("projectsUI.autoKeep")}</Button>
        </div>
      )}
      {askNote && (
        <form data-testid="projects-miss-note" className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-background px-3.5 py-2.5"
          onSubmit={e => { e.preventDefault(); if (note.trim()) onNote(note.trim()); }}>
          <span className="text-[12.5px] text-muted-foreground">{t("projectsUI.missNote", { level: miss.level ?? "" })}</span>
          <input className="min-w-[12rem] flex-1 rounded-lg border border-border bg-background px-2.5 py-1 text-[12.5px]"
            value={note} maxLength={200} placeholder={t("projectsUI.missNotePh")} aria-label={t("projectsUI.missNotePh")}
            onChange={e => setNote(e.target.value)} data-testid="projects-miss-note-input" />
          <Button size="sm" tone="primary" type="submit" disabled={busy || !note.trim()} data-testid="projects-miss-note-save">
            {t("projectsUI.missNoteSave")}</Button>
          <Button size="sm" onClick={() => skip(miss.id)} data-testid="projects-miss-note-skip">{t("projectsUI.missNoteSkip")}</Button>
        </form>
      )}
      <p data-testid="projects-shadow" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-border bg-background px-3.5 py-2.5 text-[12.5px] text-muted-foreground">
        <span className="min-w-0 flex-1">{shadow.proposed > 0
          ? t(shadow.auto_advance ? "projectsUI.shadowAuto" : "projectsUI.shadow",
            { proposed: shadow.proposed, accepted: shadow.accepted, streak: shadow.streak, askAt: shadow.ask_at })
          : t("projectsUI.shadowNone")}</span>
        <button type="button" className="font-semibold text-foreground hover:underline" onClick={onHabits}
          data-testid="projects-habits-open">{t("projectsUI.habitsOpen")}</button>
      </p>
    </div>
  );
}
