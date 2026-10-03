import { useState } from "react";
import { useTranslation } from "react-i18next";
import { lessonsApi } from "../api/lessons";

/** 0.1.52 S5: one quiet line after a turn that learned a practice — "Learned: … [Undo]",
 *  or, when it waits for the user (read from outside, or the setting is off),
 *  "Arslan wants to remember a practice: … [Remember] [No thanks]". */
export default function LearnedLine({ id, text, status }: { id: number; text: string; status: string }) {
  const { t } = useTranslation();
  const [done, setDone] = useState<"undone" | "kept" | null>(null);
  const [busy, setBusy] = useState(false);
  async function set(next: "active" | "archived") {
    setBusy(true);
    try { await lessonsApi.setStatus(id, next); setDone(next === "archived" ? "undone" : "kept"); }
    catch { /* the line stays; Brain has the same controls */ }
    finally { setBusy(false); }
  }
  const button = "ml-2 underline underline-offset-2 hover:text-foreground disabled:opacity-50";
  return (
    <p data-testid="learned-line" className="py-0.5 text-center text-[11px] text-muted-foreground">
      <span>{t(status === "proposed" ? "chat.wantsToLearn" : "chat.learned", { text })}</span>
      {done ? <span className="ml-2">{t(done === "undone" ? "chat.learnedUndone" : "chat.learnedKept")}</span>
        : status === "proposed" ? <>
          <button type="button" className={button} disabled={busy} onClick={() => void set("active")}>{t("chat.learnedKeep")}</button>
          <button type="button" className={button} disabled={busy} onClick={() => void set("archived")}>{t("chat.learnedSkip")}</button>
        </> : <button type="button" className={button} disabled={busy} onClick={() => void set("archived")}>{t("chat.learnedUndo")}</button>}
    </p>
  );
}
