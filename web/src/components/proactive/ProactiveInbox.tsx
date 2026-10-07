import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BellOff, CalendarClock, Check, Clock, FolderOpen, Globe, Inbox, ListChecks, MessageSquare, RefreshCw, Settings2, Sun, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { proactiveApi, type MuteChoice, type ProactiveItem, type ProactiveKind, type ProactiveScope } from "../../api/proactive";
import { formatUiDateTime } from "../../lib/localeFormatting";
import { evidenceLines, groupEvidence, proactiveErrorText, titleOf } from "../../lib/proactive";
import { buttonClass, primaryClass } from "../companion/CompanionDialog";
import { useDismissable } from "../../hooks/useDismissable";
import EmptyState from "../EmptyState";
import InboxApprovals from "./InboxApprovals";
import InboxMemory from "./InboxMemory";
import WatchesPanel from "./WatchesPanel";
import { Notice } from "../kit";

const ICONS: Record<ProactiveKind, typeof Globe> = {
  web_change: Globe, folder_change: FolderOpen, job_followup: ListChecks, scheduled_problem: CalendarClock, brief: Sun,
};
const TABS: { scope: ProactiveScope; label: string }[] = [
  { scope: "open", label: "proactive.page.tabOpen" }, { scope: "snoozed", label: "proactive.page.tabSnoozed" },
  { scope: "done", label: "proactive.page.tabDone" },
];
const POLL_MS = 30_000;
/** How long an item must stay in front of the user before it stops counting as unread. */
const SEEN_AFTER_MS = 1500;
const ACTIONABLE = new Set(["new", "seen", "snoozed"]);
const menuItem = "block w-full rounded px-3 py-1.5 text-left text-xs hover:bg-foreground/5";

/** A small drop-down. Closes on a choice, an outside click or Escape (the shared useDismissable),
 * which a native <details> does not do: it stayed open over the next card. */
function Menu({ label, icon, children }: { label: string; icon: React.ReactNode; children: (close: () => void) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(open, close);
  return <div className="relative">
    <button ref={anchorRef} type="button" className={buttonClass} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>{icon}{label}</button>
    {open && <div ref={floatingRef} role="menu" className="absolute left-0 z-20 mt-1 min-w-44 rounded-lg border border-border bg-background p-1 shadow-lg">{children(close)}</div>}
  </div>;
}

function Card({ item, busy, language, onDo, onSnooze, onDismiss, onOpenConversation }: {
  item: ProactiveItem; busy: boolean; language: string;
  onDo: () => void; onSnooze: (days: 1 | 3 | 7) => void; onDismiss: (mute?: MuteChoice) => void; onOpenConversation: () => void;
}) {
  const { t } = useTranslation();
  const Icon = ICONS[item.kind] ?? Inbox;
  const groups = groupEvidence(evidenceLines(t, language, item.evidence));
  const actionable = ACTIONABLE.has(item.status);
  const readOnly = item.kind === "brief";
  const when = formatUiDateTime(item.created_at, language);
  const titleId = `proactive-item-${item.id}`;
  return <article aria-labelledby={titleId} data-testid={`proactive-item-${item.id}`} data-kind={item.kind}
    className="rounded-xl border border-border bg-surface p-4">
    <div className="flex items-start gap-3">
      <Icon size={18} className="mt-0.5 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <h2 id={titleId} className="break-words text-sm font-medium">{titleOf(t, item)}</h2>
        <p className="mt-0.5 text-[11px] text-muted-foreground">{when}</p>
      </div>
      {item.priority === "high" && item.status !== "accepted" && <span className="shrink-0 rounded-full bg-ask-soft px-2 py-0.5 text-[11px] text-ask">{t("proactive.item.needsLook")}</span>}
    </div>
    <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
      {groups.map((group, index) => <li key={`${group.key}-${index}`}>
        <span>{group.text}</span>
        {group.quotes.map((quote, n) => <blockquote key={n} title={t("proactive.item.quoted")} className="mt-1 whitespace-pre-wrap break-words border-l-2 border-border pl-3 text-xs italic">“{quote}”</blockquote>)}
      </li>)}
    </ul>
    {item.diagnosis && <div data-testid="proactive-diagnosis" className="mt-3 rounded-lg bg-background/60 p-3 text-xs">
      <p className="font-medium">{t("proactive.item.guess")}</p>
      <p className="mt-1 break-words">{item.diagnosis.cause}</p>
      {item.diagnosis.next_step && <p className="mt-1 break-words">{t("proactive.item.guessNext", { step: item.diagnosis.next_step })}</p>}
      <p className="mt-1 text-[11px] text-muted-foreground">{t("proactive.item.guessNote")}</p>
    </div>}
    {actionable ? <div className="mt-4 flex flex-wrap items-center gap-2">
      {readOnly
        ? <button className={primaryClass} disabled={busy} onClick={() => onDismiss()}><Check size={14} />{t("proactive.item.gotIt")}</button>
        : <button className={primaryClass} disabled={busy} onClick={onDo}>{busy ? t("proactive.item.starting") : t("proactive.item.doIt")}</button>}
      <Menu label={t("proactive.item.snooze")} icon={<Clock size={14} />}>{(close) => <>
        {([1, 3, 7] as const).map((days) => <button key={days} role="menuitem" className={menuItem} disabled={busy}
          onClick={() => { close(); onSnooze(days); }}>{t(`proactive.item.snooze${days}`)}</button>)}
      </>}</Menu>
      {!readOnly && <Menu label={t("proactive.item.notUseful")} icon={<X size={14} />}>{(close) => <>
        <button role="menuitem" className={menuItem} disabled={busy} onClick={() => { close(); onDismiss(); }}>{t("proactive.item.dismissOnly")}</button>
        {/* A one-off job has no recurring source to silence; pages, folders and schedules do. */}
        {item.kind !== "job_followup" && <button role="menuitem" className={menuItem} disabled={busy} onClick={() => { close(); onDismiss("source"); }}>{t("proactive.item.stopSource")}</button>}
        <button role="menuitem" className={menuItem} disabled={busy} onClick={() => { close(); onDismiss("kind"); }}>{t("proactive.item.stopKind")}</button>
      </>}</Menu>}
      {item.status === "snoozed" && item.snooze_until && <span className="text-[11px] text-muted-foreground">{t("proactive.item.snoozedUntil", { date: formatUiDateTime(item.snooze_until, language) })}</span>}
    </div> : <p className="mt-4 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
      <span>{t(item.status === "accepted" ? "proactive.item.started" : item.status === "expired" ? "proactive.item.expired" : "proactive.item.dismissed")}</span>
      {item.status === "accepted" && item.conversation_id && <button className="inline-flex items-center gap-1 text-foreground underline" onClick={onOpenConversation}><MessageSquare size={12} />{t("proactive.item.openChat")}</button>}
    </p>}
  </article>;
}

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
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "info"; text: string; needsModel?: boolean } | null>(null);
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

  // What the user has had in front of them for a moment stops counting as unread.
  const unreadIds = useMemo(() => (scope === "open" ? items.filter((item) => item.status === "new").map((item) => item.id) : []), [scope, items]);
  useEffect(() => {
    if (unreadIds.length === 0) return;
    const timer = setTimeout(() => { void proactiveApi.seen(unreadIds).catch(() => { /* the badge just stays */ }); }, SEEN_AFTER_MS);
    return () => clearTimeout(timer);
  }, [unreadIds]);

  async function act(item: ProactiveItem, operation: () => Promise<unknown>) {
    setBusyId(item.id); setNotice(null);
    try { await operation(); await load(scope, true); }
    catch (cause) {
      setNotice({ kind: "error", text: proactiveErrorText(t, "item", cause), needsModel: cause instanceof ApiError && cause.message === "no_model" });
      await load(scope, true);        // whatever went wrong, show what is true now
    } finally { if (alive.current) setBusyId(null); }
  }
  const doIt = (item: ProactiveItem) => act(item, async () => {
    const fresh = item.conversation_id ? undefined : `thread-${crypto.randomUUID()}`;
    const started = await proactiveApi.accept(item.id, fresh);
    onOpenConversation(started.conversation_id, Boolean(fresh));
  });
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
  const [memoryWaiting, setMemoryWaiting] = useState(0);
  const emptyBody = scope === "open" ? t("proactive.page.emptyBody") : t(scope === "snoozed" ? "proactive.page.emptySnoozed" : "proactive.page.emptyDone");
  const card = (item: ProactiveItem) => <li key={item.id}>
    <Card item={item} busy={busyId === item.id} language={i18n.language}
      onDo={() => void doIt(item)}
      onSnooze={(days) => void act(item, () => proactiveApi.snooze(item.id, days))}
      onDismiss={(mute) => void act(item, () => proactiveApi.dismiss(item.id, mute))}
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
  const nothing = !loading && !failed && items.length === 0 && waiting === 0 && memoryWaiting === 0;
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
      {open && <InboxApprovals onCount={setWaiting} onOpenConversation={(id) => onOpenConversation(id, false)} />}
      {loading && !failed && <p role="status" className="text-sm text-muted-foreground">{t("companion.loading")}</p>}
      {nothing && <EmptyState icon={open ? Inbox : BellOff} title={t("proactive.page.emptyTitle")} body={emptyBody}
        action={open ? <button className={primaryClass} onClick={onOpenSettings}>{t("proactive.page.emptyAction")}</button> : undefined} testId="proactive-empty" />}
      {open ? <>
        {group("inbox.stalled", "bg-danger-strong", stalled)}
        {group("inbox.changed", "bg-info-strong", changed)}
        {group("inbox.other", "bg-subtle-foreground", rest)}
        <InboxMemory onCount={setMemoryWaiting} />
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
