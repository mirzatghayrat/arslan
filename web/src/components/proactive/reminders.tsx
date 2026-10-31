import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarClock, Check, Clock, FolderOpen, Globe, Inbox, ListChecks, MessageSquare, Sun, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { proactiveApi, type MuteChoice, type ProactiveItem, type ProactiveKind } from "../../api/proactive";
import { formatUiDateTime } from "../../lib/localeFormatting";
import { evidenceLines, groupEvidence, proactiveErrorText, titleOf } from "../../lib/proactive";
import { buttonClass, primaryClass } from "../companion/CompanionDialog";
import { useDismissable } from "../../hooks/useDismissable";
import { Escaped, isolate } from "../../lib/outsideText";

// INB3: a reminder's card and what its buttons do, moved here from ProactiveInbox (the INB card: extract, then delete) so the
// Scheduled page shows a task's problem and a watch's change the same way. The Inbox uses them too until INB5 removes it.

const ICONS: Record<ProactiveKind, typeof Globe> = {
  web_change: Globe, folder_change: FolderOpen, job_followup: ListChecks, scheduled_problem: CalendarClock, brief: Sun,
};
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

export function ReminderCard({ item, busy, language, onDo, onSnooze, onDismiss, onOpenConversation }: {
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
        {group.quotes.map((quote, n) => <blockquote key={n} title={t("proactive.item.quoted")} className="mt-1 whitespace-pre-wrap break-words border-l-2 border-border pl-3 text-xs italic">“<Escaped text={quote} />”</blockquote>)}
      </li>)}
    </ul>
    {item.diagnosis && <div data-testid="proactive-diagnosis" className="mt-3 rounded-lg bg-background/60 p-3 text-xs">
      <p className="font-medium">{t("proactive.item.guess")}</p>
      <p className="mt-1 break-words"><Escaped text={item.diagnosis.cause} /></p>
      {item.diagnosis.next_step && <p className="mt-1 break-words">{t("proactive.item.guessNext", { step: isolate(item.diagnosis.next_step) })}</p>}
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

export type ReminderNotice = { kind: "error" | "info"; text: string; needsModel?: boolean };

/** What a reminder's buttons do: "Do it" starts the job (in a new conversation when the item has none), snooze and dismiss
 *  change the item; after each, `reload` shows what is true now. */
export function useReminderActions({ reload, onOpenConversation }: {
  reload: () => Promise<unknown>;
  /** `created` is true when the app must first make a conversation with this id for the job to report into. */
  onOpenConversation: (conversationId: string, created: boolean) => void;
}) {
  const { t } = useTranslation();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState<ReminderNotice | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  async function act(item: ProactiveItem, operation: () => Promise<unknown>) {
    setBusyId(item.id); setNotice(null);
    try { await operation(); await reload(); }
    catch (cause) {
      setNotice({ kind: "error", text: proactiveErrorText(t, "item", cause), needsModel: cause instanceof ApiError && cause.message === "no_model" });
      await reload();                 // whatever went wrong, show what is true now
    } finally { if (alive.current) setBusyId(null); }
  }
  const doIt = (item: ProactiveItem) => act(item, async () => {
    const fresh = item.conversation_id ? undefined : `thread-${crypto.randomUUID()}`;
    const started = await proactiveApi.accept(item.id, fresh);
    onOpenConversation(started.conversation_id, Boolean(fresh));
  });
  const snooze = (item: ProactiveItem, days: 1 | 3 | 7) => act(item, () => proactiveApi.snooze(item.id, days));
  const dismiss = (item: ProactiveItem, mute?: MuteChoice) => act(item, () => proactiveApi.dismiss(item.id, mute));
  return { busyId, notice, setNotice, doIt, snooze, dismiss };
}
