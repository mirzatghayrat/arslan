import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ScheduledTaskDto } from "../../api/client.types";
import { proactiveApi, type ProactiveItem } from "../../api/proactive";
import { AWAY_HOURS, scheduledConversation, type ScheduledAttention } from "../../hooks/useScheduledAttention";
import { proactiveErrorText } from "../../lib/proactive";
import RunDrawer from "../activity/RunDrawer";
import { buttonClass } from "../companion/CompanionDialog";
import { Notice } from "../kit";
import NotDoneList from "../proactive/NotDoneList";
import WatchesPanel from "../proactive/WatchesPanel";
import { ReminderCard, useReminderActions } from "../proactive/reminders";
import ScheduledTasksCard from "../ScheduledTasksCard";

/**
 * INB3: the scheduled tasks and the pages and folders Arslan watches, in one place (the INB card, item 3). A row carries a dot when
 * it needs a look: a task whose run failed or that paused itself, has a problem reminder, or could not do something while nobody
 * was there; a watch whose page or folder changed. A task's problem and its away entries show under its runs, a change under its
 * watch with the guess and next step. "Check now" lives here.
 */
export default function ScheduledPage({ attention, onOpenConversation, onOpenModelSettings }: {
  attention: ScheduledAttention;
  /** `created` is true when the app must first make a conversation with this id for the job to report into. */
  onOpenConversation: (conversationId: string, created: boolean) => void;
  /** Where "add a model first" sends the user. */
  onOpenModelSettings?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [openRun, setOpenRun] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);
  const { busyId, notice, setNotice, doIt, snooze, dismiss } = useReminderActions({ reload: attention.reload, onOpenConversation });
  const reminder = (item: ProactiveItem) => <ReminderCard key={item.id} item={item} busy={busyId === item.id} language={i18n.language}
    onDo={() => void doIt(item)} onSnooze={(days) => void snooze(item, days)} onDismiss={(mute) => void dismiss(item, mute)}
    onOpenConversation={() => item.conversation_id && onOpenConversation(item.conversation_id, false)} />;
  const needsLook = (task: ScheduledTaskDto) => {
    const a = attention.tasks[task.id];
    if (!a) return null;
    if (a.failing) return "failing";                                   // red, as the board drew a task that paused itself
    return a.problems.length > 0 || a.away > 0 ? "look" : null;
  };

  async function checkNow() {
    setChecking(true); setNotice(null);
    try {
      const { created } = await proactiveApi.scan();
      setNotice({ kind: "info", text: t(created === 0 ? "proactive.page.checkedNone" : "proactive.page.checkedSome", { count: created }) });
      await attention.reload();
    } catch (cause) { setNotice({ kind: "error", text: proactiveErrorText(t, "item", cause) }); }
    finally { setChecking(false); }
  }

  return <section data-testid="scheduled-page" className="h-full overflow-y-auto px-5 py-6 sm:px-8">
    <div className="mx-auto max-w-[860px] space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold">{t("nav.scheduled")}</h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">{t("scheduledPage.intro")}</p>
        </div>
        <button className={buttonClass} disabled={checking} onClick={() => void checkNow()}>
          <RefreshCw size={14} className={checking ? "animate-spin" : ""} />{t(checking ? "proactive.page.checking" : "proactive.page.checkNow")}</button>
      </div>
      {notice && <Notice tone={notice.kind === "error" ? "error" : "info"}
        action={notice.needsModel && onOpenModelSettings ? <button className="text-[13px] underline" onClick={onOpenModelSettings}>{t("proactive.item.errors.openModels")}</button> : undefined}>
        {notice.text}</Notice>}
      <ScheduledTasksCard onOpenRun={setOpenRun} attention={needsLook} details={(task) => <div className="mt-3 space-y-3">
        {(attention.tasks[task.id]?.problems ?? []).map(reminder)}
        <NotDoneList conversationId={scheduledConversation(task)} hours={AWAY_HOURS} unattended title={t("scheduledPage.awayTitle")} />
      </div>} />
      <section aria-labelledby="scheduled-watches" className="space-y-3">
        <h2 id="scheduled-watches" className="text-[13px] font-semibold text-muted-foreground">{t("scheduledPage.watches")}</h2>
        <WatchesPanel quiet marked={(watch) => (attention.changes[watch.id]?.length ?? 0) > 0}
          below={(watch) => attention.changes[watch.id]?.length
            ? <div className="mt-3 space-y-2">{attention.changes[watch.id].map(reminder)}</div> : null} />
      </section>
    </div>
    {openRun != null && <RunDrawer runId={openRun} onClose={() => setOpenRun(null)} />}
  </section>;
}
