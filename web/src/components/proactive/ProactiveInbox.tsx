import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BellOff, Inbox, RefreshCw, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { proactiveApi, type ProactiveItem, type ProactiveScope } from "../../api/proactive";
import { proactiveErrorText } from "../../lib/proactive";
import { buttonClass, primaryClass } from "../companion/CompanionDialog";
import EmptyState from "../EmptyState";
import InboxApprovals from "./InboxApprovals";
import InboxRefused from "./InboxRefused";
import WatchesPanel from "./WatchesPanel";
import { ReminderCard, useReminderActions } from "./reminders";
import { AnswerGuardScope, Notice, useAnswerGuardState } from "../kit";

const TABS: { scope: ProactiveScope; label: string }[] = [
  { scope: "open", label: "proactive.page.tabOpen" }, { scope: "snoozed", label: "proactive.page.tabSnoozed" },
  { scope: "done", label: "proactive.page.tabDone" },
];
const POLL_MS = 30_000;
/** How long an item must stay in front of the user before it stops counting as unread. */
const SEEN_AFTER_MS = 1500;
export default function ProactiveInbox({ onOpenSettings, onOpenModelSettings, onOpenConversation }: {
  onOpenSettings: () => void;
  /** Where "add a model first" sends the user. */
  onOpenModelSettings?: () => void;
  /** `created` is true when the app must first make a conversation with this id for the job to report into. */
  onOpenConversation: (conversationId: string, created: boolean) => void;
}) {
  const { t, i18n } = useTranslation();
  const [scope, setScope] = useState<ProactiveScope>("open");
  const [items, setItems] = useState<ProactiveItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [checking, setChecking] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const load = useCallback(async (which: ProactiveScope, quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const body = await proactiveApi.items(which);
      if (alive.current) { setItems(body.items); setFailed(false); }
    } catch { if (alive.current) setFailed(true); }
    finally { if (alive.current && !quiet) setLoading(false); }
  }, []);
  useEffect(() => {
    void load(scope);
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(scope, true); }, POLL_MS);
    return () => clearInterval(timer);
  }, [scope, load]);

  const { busyId, notice, setNotice, doIt, snooze, dismiss } = useReminderActions({ reload: () => load(scope, true), onOpenConversation });
  // What the user has had in front of them for a moment stops counting as unread.
  const unreadIds = useMemo(() => (scope === "open" ? items.filter((item) => item.status === "new").map((item) => item.id) : []), [scope, items]);
  useEffect(() => {
    if (unreadIds.length === 0) return;
    const timer = setTimeout(() => { void proactiveApi.seen(unreadIds).catch(() => { /* the badge just stays */ }); }, SEEN_AFTER_MS);
    return () => clearTimeout(timer);
  }, [unreadIds]);

  async function checkNow() {
    setChecking(true); setNotice(null);
    try {
      const { created } = await proactiveApi.scan();
      setNotice({ kind: "info", text: t(created === 0 ? "proactive.page.checkedNone" : "proactive.page.checkedSome", { count: created }) });
      await load(scope, true);
    } catch (cause) { setNotice({ kind: "error", text: proactiveErrorText(t, "item", cause) }); }
    finally { if (alive.current) setChecking(false); }
  }

  const [waiting, setWaiting] = useState(0);
  const [refused, setRefused] = useState(0);
  // 0.1.61 §A4: the waiting cards and "Not done while you were away" sit one above the other, so a change in either moves the other under
  // the pointer. One guard holds both: one gesture answers one thing, across the two (kit/guard.ts).
  const inboxGuard = useAnswerGuardState();
  const emptyBody = scope === "open" ? t("proactive.page.emptyBody") : t(scope === "snoozed" ? "proactive.page.emptySnoozed" : "proactive.page.emptyDone");
  const card = (item: ProactiveItem) => <li key={item.id}>
    <ReminderCard item={item} busy={busyId === item.id} language={i18n.language}
      onDo={() => void doIt(item)}
      onSnooze={(days) => void snooze(item, days)}
      onDismiss={(mute) => void dismiss(item, mute)}
      onOpenConversation={() => item.conversation_id && onOpenConversation(item.conversation_id, false)} />
  </li>;
  // 0.1.55 §12: grouped by what the user has to decide, not by where it came from.
  const open = scope === "open";
  const briefs = open ? items.filter((i) => i.kind === "brief") : [];
  const stalled = open ? items.filter((i) => i.kind === "job_followup" || i.kind === "scheduled_problem") : [];
  const changed = open ? items.filter((i) => i.kind === "web_change" || i.kind === "folder_change") : [];
  const rest = open ? items.filter((i) => !briefs.includes(i) && !stalled.includes(i) && !changed.includes(i)) : items;
  const group = (key: string, dot: string, list: ProactiveItem[]) => list.length > 0 && <section aria-label={t(key)} className="flex flex-col gap-2">
    <h2 className="flex items-center gap-2 text-[13px] font-semibold">
      <span aria-hidden="true" className={`h-[7px] w-[7px] rounded-full ${dot}`} />{t(key)}
      <span className="font-mono text-[12px] text-subtle-foreground">{list.length}</span></h2>
    <ul className="space-y-3">{list.map(card)}</ul>
  </section>;
  const nothing = !loading && !failed && items.length === 0 && waiting === 0 && refused === 0;
  return <section data-testid="proactive-inbox" className="h-full overflow-y-auto px-5 py-6 sm:px-8">
    <div className="mx-auto flex max-w-6xl gap-7">
    <div className="min-w-0 max-w-[700px] flex-1 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0"><h1 className="text-xl font-semibold">{t("proactive.page.title")}</h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">{t("proactive.page.intro")}</p></div>
        <div className="flex gap-2">
          <button className={buttonClass} disabled={checking} onClick={() => void checkNow()}><RefreshCw size={14} className={checking ? "animate-spin" : ""} />{t(checking ? "proactive.page.checking" : "proactive.page.checkNow")}</button>
          <button className={buttonClass} aria-label={t("settings.navProactive")} title={t("settings.navProactive")} onClick={onOpenSettings}><Settings2 size={14} /></button>
        </div>
      </div>
      <div role="tablist" className="flex gap-1 border-b border-border">
        {TABS.map((tab) => <button key={tab.scope} role="tab" aria-selected={scope === tab.scope} onClick={() => setScope(tab.scope)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${scope === tab.scope ? "border-foreground font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{t(tab.label)}</button>)}
      </div>
      {notice && <Notice tone={notice.kind === "error" ? "error" : "info"}
        action={notice.needsModel && onOpenModelSettings ? <button className="text-[13px] underline" onClick={onOpenModelSettings}>{t("proactive.item.errors.openModels")}</button> : undefined}>
        {notice.text}</Notice>}
      {failed && <p role="alert" className="text-sm text-danger-strong">{t("proactive.page.loadFailed")} <button className="underline" onClick={() => void load(scope)}>{t("proactive.page.retry")}</button></p>}
      <AnswerGuardScope value={inboxGuard}>
        {open && <InboxApprovals onCount={setWaiting} onOpenConversation={(id) => onOpenConversation(id, false)} />}
        {open && <InboxRefused onCount={setRefused} />}
      </AnswerGuardScope>
      {loading && !failed && <p role="status" className="text-sm text-muted-foreground">{t("companion.loading")}</p>}
      {nothing && <EmptyState icon={open ? Inbox : BellOff} title={t("proactive.page.emptyTitle")} body={emptyBody}
        action={open ? <button className={primaryClass} onClick={onOpenSettings}>{t("proactive.page.emptyAction")}</button> : undefined} testId="proactive-empty" />}
      {open ? <>
        {group("inbox.stalled", "bg-danger-strong", stalled)}
        {group("inbox.changed", "bg-info-strong", changed)}
        {group("inbox.other", "bg-subtle-foreground", rest)}
      </> : <ul className="space-y-4">{items.map(card)}</ul>}
    </div>
    <aside data-testid="inbox-side" className="hidden w-[300px] shrink-0 flex-col gap-5 lg:flex">
      {briefs.length > 0 && <ul className="space-y-3">{briefs.map(card)}</ul>}
      <div className="flex flex-col gap-2">
        <h2 className="text-[13px] font-semibold text-muted-foreground">{t("inbox.watching")}</h2>
        <WatchesPanel quiet />
      </div>
    </aside>
    </div>
  </section>;
}
