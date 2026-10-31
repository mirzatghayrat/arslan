import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { proactiveApi, type ProactiveItem } from "../../api/proactive";
import NotDoneList from "../proactive/NotDoneList";
import { ReminderCard, useReminderActions } from "../proactive/reminders";
import { Notice } from "../kit";

// INB5b (v0.1.64): what waited in the Inbox comes back to its conversation (the INB5 board, approved 2026-10-31). Approval cards
// were already there; these two pieces join them.

/** How long "not done while you were away" stays listed: the window the Inbox always used, and the badge's (progress.AWAY_HOURS). */
const AWAY_HOURS = 24;
const POLL_MS = 30_000;

/** What wasn't done while you were away, on top of the conversation: its own cards that went unanswered, not a scheduled run's
 *  (those are its task's, on the Scheduled page). Nothing at all when nothing waits. */
export function AwayEntries({ conversationId }: { conversationId: string }) {
  const { t } = useTranslation();
  return <NotDoneList conversationId={conversationId} hours={AWAY_HOURS} awayOnly title={t("whileAway.title")}
    className="mx-auto w-full max-w-3xl rounded-xl border border-border bg-surface p-4" />;
}

/** A job that stopped here: its card sits in the conversation with 「接着做」/「先放着」/「不用了」 (the shared reminder card). A card set
 *  aside or handled stays on its row with its state (Q7), so nothing about it needs a list of its own. */
export function StoppedJobCards({ conversationId, onOpenConversation, onOpenModelSettings }: {
  conversationId: string;
  /** `created` is true when the app must first make a conversation with this id for the job to report into. */
  onOpenConversation: (conversationId: string, created: boolean) => void;
  /** Where "add a model first" sends the user. */
  onOpenModelSettings?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [items, setItems] = useState<ProactiveItem[]>([]);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(async () => {
    try {
      const body = await proactiveApi.items("all", { conversationId, kind: "job_followup" });
      if (alive.current) setItems([...body.items].sort((a, b) => a.id - b.id));       // oldest first, as the conversation reads
    } catch { /* an older server has no such filter: the conversation still works */ }
  }, [conversationId]);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);
  const { busyId, notice, doIt, snooze, dismiss } = useReminderActions({ reload: load, onOpenConversation });
  if (items.length === 0 && !notice) return null;
  return <section aria-label={t("whileAway.stopped")} className="mx-auto flex w-full max-w-3xl flex-col gap-3">
    {notice && <Notice tone={notice.kind === "error" ? "error" : "info"}
      action={notice.needsModel && onOpenModelSettings
        ? <button className="text-[13px] underline" onClick={onOpenModelSettings}>{t("proactive.item.errors.openModels")}</button> : undefined}>
      {notice.text}</Notice>}
    {items.map((item) => <ReminderCard key={item.id} item={item} busy={busyId === item.id} language={i18n.language}
      onDo={() => void doIt(item)} onSnooze={(days) => void snooze(item, days)} onDismiss={(mute) => void dismiss(item, mute)}
      onOpenConversation={() => onOpenConversation(conversationId, false)} />)}
  </section>;
}
