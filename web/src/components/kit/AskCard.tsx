import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUpRight, Lock } from "lucide-react";
import { Button } from "./Button";
import { CARD_MS, Countdown } from "./Countdown";
import { useAnswerGuard, useAnswerHeld } from "./guard";
import { SURFACE, useAnswerKeys, useLayer } from "./layers";

export interface AskQueuePosition { index: number; total: number; onPrev?: () => void; onNext?: () => void }

/** SMART-8: how hard a step is to take back, for the 「风险」 row's colour (orange to warn, red for irreversible). */
export type AskRiskLevel = "info" | "warn" | "irreversible";

/** SMART-8: a choice besides the two answers, drawn as a secondary button after the primary one. */
/** Another approval beside Allow: off while Allow is (`allowDisabled`), red when `destructive`
 *  (PR 688's review, item 8). */
export interface AskAction { label: string; onClick: () => void; testId?: string; destructive?: boolean }

export interface AskCardProps {
  /** Who is asking: "Arslan 在问你" / "后台作业在问你". The card's accessible name; SMART-8 (the user: drop the small heading)
   *  no longer prints it as a heading. */
  who: string;
  /** One plain sentence: what Arslan wants to do. */
  title: ReactNode;
  /** SMART-8: where `title` came from, shown under it: Arslan's own reason for the step (the model's words), or read
   *  from the command by code. Absent on a card whose title is the server's own sentence. */
  purposeFrom?: "arslan" | "command";
  /** SMART-8: what the step touches (a host, a folder or file, a recipient), read by code: the 「涉及」 row. */
  touches?: ReactNode;
  /** SMART-8: the 「风险」 row, in plain words, read by code. With it, `risk` (the amber box) is not drawn. */
  riskRow?: { level: AskRiskLevel; text: ReactNode };
  /** SMART-8: the raw command (or the text to be sent), folded under "Show command" and shown whole when opened. */
  folded?: { body: ReactNode; showLabel?: string; hideLabel?: string; testId?: string };
  /** SMART-8: more choices, as secondary buttons after the primary one. */
  actions?: AskAction[];
  /** The MODEL's own description, never trusted for safety: shown as "Arslan 说：…". */
  said?: string | null;
  /** Derived from the code / command itself (decision 1): amber, with a lock. */
  risk?: string | null;
  /** Folded detail: a CodeBox, a path, a fingerprint, a form. */
  detail?: ReactNode;
  /** Context lines: which job, the scope of the grant, what still asks. */
  context?: { icon?: ReactNode; text: ReactNode }[];
  /** Options such as "don't ask again in this conversation". */
  options?: ReactNode;
  expiresAt?: number | null;
  totalMs?: number;
  queue?: AskQueuePosition;
  allowLabel?: string;
  declineLabel?: string;
  /** The allow action destroys or sends (shown red). */
  destructive?: boolean;
  onAllow: () => void;
  onDecline: () => void;
  /** This card's own answer is in flight (an apply over REST): Allow, No and the keys are off. Never the pager — paging and the other cards stay free. */
  busy?: boolean;
  /** Only the allow answer is not possible yet (e.g. a required key is empty); esc still declines. */
  allowDisabled?: boolean;
  /** "See the whole context" (island, inbox → the conversation). */
  onOpenContext?: () => void;
  /** Extra actions beside the two answers. */
  extra?: ReactNode;
  /** Answers to ⌘⏎ / esc while it is the top surface. Off when shown as a preview. */
  keys?: boolean;
  testId?: string;
  /** Extra attributes on the card (e.g. data-kind), and stable test ids for the two answers. */
  attrs?: Record<string, string>;
  allowTestId?: string;
  saidTestId?: string;
  declineTestId?: string;
  /** CAP9: No is the safe answer, so it leads as the primary wide button and is focused on mount — unless the user is
   *  typing, another surface owns focus, or a modal is open. */
  safeDefault?: boolean;
  /** ⌘⏎ allows only when true (the default). A risky install (CAP9) sets it false, so only a deliberate Tab then Enter
   *  or a click confirms the install (Esc still declines). */
  allowKey?: boolean;
  className?: string;
}

/**
 * AskCard — the one shape of "Arslan needs your OK" (0.1.55 surface kit, spec §2).
 * Replaces the RunCommandCard variants, ActionApprovalCard kinds, WorkspaceWriteCard,
 * ScheduleGrantCard, EnrollNodeCard and the phone pairing request.
 */
export function AskCard(p: AskCardProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const top = useLayer(p.keys !== false);
  const root = useRef<HTMLElement>(null);
  const saidId = useId();
  // Within ANSWER_GUARD_MS of this card coming up in a queue, no answer is for it (see guard.ts).
  const guarded = useAnswerGuard();
  const held = useAnswerHeld();                                     // the same hold, to be seen: Allow and No look disabled while it lasts
  const allowKey = p.allowKey !== false;
  useAnswerKeys(top && !p.busy, { onAllow: allowKey ? () => { if (!p.allowDisabled && !guarded()) p.onAllow(); } : undefined,
                                  onDecline: () => { if (!guarded()) p.onDecline(); } }, root);
  useEffect(() => {
    if (!p.safeDefault) return;
    const active = document.activeElement;
    const typing = active instanceof HTMLElement && (active.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName));
    // CAP9 review: don't pull focus out of another surface — an open dialog or another card owns its own focus, and a
    // modal owns it even when nothing in it is focused yet, so skip if focus is on another surface or any modal is open
    // outside this card.
    const onAnother = active instanceof Element && active.closest(SURFACE) !== null && active.closest(SURFACE) !== root.current;
    const modalOutside = Array.from(document.querySelectorAll('[aria-modal="true"]')).some((m) => !root.current?.contains(m));
    if (!typing && !onAnother && !modalOutside) root.current?.querySelector<HTMLButtonElement>(`[data-testid="${p.declineTestId ?? "ask-decline"}"]`)?.focus();
  }, [p.safeDefault, p.declineTestId]);
  return (
    <section ref={root} data-testid={p.testId ?? "ask-card"} role="alertdialog" aria-label={p.who}
      aria-describedby={p.said ? saidId : undefined} {...p.attrs}
      className={`flex w-full max-w-[460px] flex-col gap-3.5 rounded-2xl border border-border bg-surface px-5 pb-4 pt-[18px] text-foreground shadow-kit ${p.className ?? ""}`}>
      {/* The default asker ("Arslan is asking") is no longer printed (the user: drop the small heading); another one (a background
          job) still is, as it is the only place some cards say who is asking. */}
      {(p.queue && p.queue.total > 1) || p.expiresAt || p.who !== t("kit.whoArslan") ? <header
        className="flex items-center justify-between gap-3">
        <span data-testid="ask-who" className="truncate text-[12px] font-semibold text-ask">
          {p.who !== t("kit.whoArslan") ? p.who : null}</span>
        <div className="flex items-center gap-2.5">
          {p.queue && p.queue.total > 1 && (
            <span data-testid="ask-queue" className="inline-flex items-center gap-1.5 font-mono text-[12px] text-muted-foreground">
              <button type="button" data-nav="prev" aria-label={t("kit.previous")} disabled={!p.queue.onPrev} onClick={p.queue.onPrev}
                className="px-0.5 hover:text-foreground disabled:opacity-40">‹</button>
              {t("kit.queueOf", { index: p.queue.index + 1, total: p.queue.total })}
              <button type="button" data-nav="next" aria-label={t("kit.next")} disabled={!p.queue.onNext} onClick={p.queue.onNext}
                className="px-0.5 hover:text-foreground disabled:opacity-40">›</button>
            </span>
          )}
          {p.expiresAt ? <Countdown expiresAt={p.expiresAt} totalMs={p.totalMs ?? CARD_MS} /> : null}
        </div>
      </header> : null}
      <div className="flex flex-col gap-1">
        <h3 className="text-[16px] font-semibold leading-[1.45] [overflow-wrap:anywhere]">{p.title}</h3>
        {p.purposeFrom ? <span data-testid="ask-purpose-from" className="text-[11px] text-muted-foreground">
          {t(p.purposeFrom === "arslan" ? "kit.purposeFromArslan" : "kit.purposeFromCommand")}</span> : null}
      </div>
      {p.said ? (
        <p id={saidId} data-testid={p.saidTestId ?? "ask-said"} className="-mt-1.5 text-[13px] text-muted-foreground [overflow-wrap:anywhere]">
          <span className="text-subtle-foreground">{t("kit.arslanSays")}</span>{p.said}
        </p>
      ) : null}
      {p.touches || p.riskRow ? (
        <div data-testid="ask-rows" className="grid grid-cols-[56px_minmax(0,1fr)] gap-x-3 gap-y-2 text-[13px] leading-[1.5]">
          {p.touches ? <>
            <span className="text-muted-foreground">{t("kit.touches")}</span>
            <span data-testid="ask-touches" className="min-w-0 [overflow-wrap:anywhere]">{p.touches}</span>
          </> : null}
          {p.riskRow ? <>
            <span className={p.riskRow.level === "irreversible" ? "font-semibold text-danger"
              : p.riskRow.level === "warn" ? "font-semibold text-ask" : "text-muted-foreground"}>{t("kit.riskLabel")}</span>
            <span data-testid="ask-risk-row" data-level={p.riskRow.level} className={p.riskRow.level === "irreversible"
              ? "text-danger" : p.riskRow.level === "warn" ? "text-ask" : ""}>{p.riskRow.text}</span>
          </> : null}
        </div>
      ) : null}
      {p.risk && !p.riskRow ? (
        <div data-testid="ask-risk" className="flex items-center gap-2 rounded-[10px] bg-ask-soft px-3 py-2 text-[13px] font-semibold text-ask">
          <Lock size={15} aria-hidden="true" className="shrink-0" />
          <span>{p.risk}</span>
        </div>
      ) : null}
      {p.folded ? <div className="flex flex-col gap-2">
        <button type="button" data-testid={p.folded.testId ?? "ask-fold"} aria-expanded={open} onClick={() => setOpen(!open)}
          className="self-start text-[12px] text-primary hover:underline">
          {open ? (p.folded.hideLabel ?? t("kit.hideCommand")) : (p.folded.showLabel ?? t("kit.showCommand"))}</button>
        {/* Kept in the page while folded, so it is the card's own text (find, tests), just not drawn. */}
        <div hidden={!open} data-testid="ask-folded-body">{p.folded.body}</div>
      </div> : null}
      {p.detail}
      {p.context && p.context.length > 0 && (
        <ul className="flex flex-col gap-[7px] text-[13px] text-muted-foreground">
          {p.context.map((c, i) => (
            <li key={i} className="flex items-center gap-2">{c.icon}<span>{c.text}</span></li>
          ))}
        </ul>
      )}
      {p.options}
      {/* SMART-8 (the mock the user OK'd): the action first, named for what it does; then any other choice; No last.
          CAP9 (safeDefault): No is the safe answer, so it leads as the primary wide button and the action is de-emphasised. */}
      <div className="flex flex-wrap gap-2.5">
        {p.safeDefault && (
          <Button tone="primary" grow={1.4} kbd="esc" disabled={p.busy} aria-disabled={held || undefined}
            onClick={() => { if (!guarded()) p.onDecline(); }} data-testid={p.declineTestId ?? "ask-decline"}>
            {p.declineLabel ?? t("kit.decline")}
          </Button>
        )}
        <Button tone={p.destructive ? "destructive" : p.safeDefault ? "secondary" : "primary"} grow={p.safeDefault ? 1 : 1.4}
          kbd={allowKey ? "⌘⏎" : undefined} disabled={p.busy || p.allowDisabled} aria-disabled={held || undefined}
          onClick={() => { if (!guarded()) p.onAllow(); }} data-testid={p.allowTestId ?? "ask-allow"}>
          {p.allowLabel ?? t("kit.allow")}
        </Button>
        {p.actions?.map((a, i) => (
          <Button key={i} tone={a.destructive ? "destructive" : "secondary"} grow={1} disabled={p.busy || p.allowDisabled}
            aria-disabled={held || undefined}
            onClick={() => { if (!guarded()) a.onClick(); }} data-testid={a.testId}>{a.label}</Button>
        ))}
        {!p.safeDefault && (
          <Button tone="secondary" grow={1} kbd="esc" disabled={p.busy} aria-disabled={held || undefined}
            onClick={() => { if (!guarded()) p.onDecline(); }} data-testid={p.declineTestId ?? "ask-decline"}>
            {p.declineLabel ?? t("kit.decline")}
          </Button>
        )}
      </div>
      {p.extra}
      {p.onOpenContext && (
        <button type="button" onClick={p.onOpenContext}
          className="mx-auto inline-flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground">
          {t("kit.seeContext")} <ArrowUpRight size={12} aria-hidden="true" />
        </button>
      )}
    </section>
  );
}
