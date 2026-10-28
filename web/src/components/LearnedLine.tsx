import { useState } from "react";
import { useTranslation } from "react-i18next";
import { lessonsApi } from "../api/lessons";
import { openSection } from "../lib/sections";

/** 0.1.52 S5: one quiet line after a turn that learned a practice — "Learned: … [Undo]".
 *  v0.1.64 (INB1): a practice that did not take effect no longer asks "remember or not": the line says
 *  why ("Learned one, not in effect: <reason>") and links to Memory, where it can be read in full and
 *  switched on. */
export default function LearnedLine({ id, text, status, notInEffect }: {
  id: number; text: string; status: string; notInEffect?: string | null;
}) {
  const { t } = useTranslation();
  const [undone, setUndone] = useState(false);
  const [busy, setBusy] = useState(false);
  async function undo() {
    setBusy(true);
    try { await lessonsApi.setStatus(id, "archived"); setUndone(true); }
    catch { /* the line stays; Memory has the same controls */ }
    finally { setBusy(false); }
  }
  const button = "ml-2 underline underline-offset-2 hover:text-foreground disabled:opacity-50";
  if (status !== "active") {
    return (
      <p data-testid="learned-line" className="py-0.5 text-center text-[11px] text-muted-foreground">
        <span>{t("chat.learnedNotInEffect", { reason: t(`companion.why_${notInEffect || "outside_content"}`) })}</span>
        <button type="button" className={button} onClick={() => openSection("brain")}>{t("chat.learnedSeeInMemory")}</button>
      </p>
    );
  }
  return (
    <p data-testid="learned-line" className="py-0.5 text-center text-[11px] text-muted-foreground">
      <span>{t("chat.learned", { text })}</span>
      {undone ? <span className="ml-2">{t("chat.learnedUndone")}</span>
        : <button type="button" className={button} disabled={busy} onClick={() => void undo()}>{t("chat.learnedUndo")}</button>}
    </p>
  );
}
