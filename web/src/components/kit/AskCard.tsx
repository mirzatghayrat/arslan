import { useEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUpRight, Lock } from "lucide-react";
import { AskMark } from "./AskMark";
import { Button } from "./Button";
import { CARD_MS, Countdown } from "./Countdown";
import { useAnswerGuard, useAnswerHeld } from "./guard";
import { SURFACE, useAnswerKeys, useLayer } from "./layers";

export interface AskQueuePosition { index: number; total: number; onPrev?: () => void; onNext?: () => void }

export interface AskCardProps {
  /** Who is asking: "Arslan 在问你" / "后台作业在问你". */
  who: string;
  /** One plain sentence: what Arslan wants to do. */
  title: ReactNode;
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
  /** Extra actions beside the two answers (e.g. "run again outside the sandbox"). */
  extra?: ReactNode;
  /** Answers to ⌘⏎ / esc while it is the top surface. Off when shown as a preview. */
  keys?: boolean;
  /** CAP9 (the user's question 5): ⌘⏎ does not answer Allow, and its hint is not drawn. The card stays the top
   *  surface (another card behind it never takes the key), and esc still answers No. */
  allowKey?: boolean;
  /** CAP9: No is the safe answer: drawn as the primary, wide button, and focused unless the user is typing. */
  safeDefault?: boolean;
  testId?: string;
  /** Extra attributes on the card (e.g. data-kind), and stable test ids for the two answers. */
  attrs?: Record<string, string>;
  allowTestId?: string;
  saidTestId?: string;
  declineTestId?: string;
  className?: string;
}

/**
 * AskCard — the one shape of "Arslan needs your OK" (0.1.55 surface kit, spec §2).
 * Replaces the RunCommandCard variants, ActionApprovalCard kinds, WorkspaceWriteCard,
 * ScheduleGrantCard, EnrollNodeCard and the phone pairing request.
 */
export function AskCard(p: AskCardProps) {
  const { t } = useTranslation();
  const top = useLayer(p.keys !== false);
  const root = useRef<HTMLElement>(null);
  // Within ANSWER_GUARD_MS of this card coming up in a queue, no answer is for it (see guard.ts).
  const guarded = useAnswerGuard();
  const held = useAnswerHeld();                                     // the same hold, to be seen: Allow and No look disabled while it lasts
  const allowKey = p.allowKey !== false;
  useAnswerKeys(top && !p.busy, { onAllow: allowKey ? () => { if (!p.allowDisabled && !guarded()) p.onAllow(); } : undefined,
                                  onDecline: () => { if (!guarded()) p.onDecline(); } }, root);
  const declineId = p.declineTestId ?? "ask-decline";
  useEffect(() => {
    if (!p.safeDefault) return;
    const active = document.activeElement;
    const typing = active instanceof HTMLElement && (active.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName));
    // #661 review: don't pull focus out of another surface — an open dialog or another card owns its own focus.
    const onAnother = active instanceof Element && active.closest(SURFACE) !== null && active.closest(SURFACE) !== root.current;
    if (!typing && !onAnother) root.current?.querySelector<HTMLButtonElement>(`[data-testid="${declineId}"]`)?.focus();
  }, [p.safeDefault, declineId]);
  return (
    <section ref={root} data-testid={p.testId ?? "ask-card"} role="alertdialog" aria-label={p.who} {...p.attrs}
      className={`flex w-full max-w-[460px] flex-col gap-3.5 rounded-2xl border border-border bg-surface px-5 pb-4 pt-[18px] text-foreground shadow-kit ${p.className ?? ""}`}>
      <header className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <AskMark />
          <span className="truncate text-[13px] font-semibold text-ask">{p.who}</span>
        </div>
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
      </header>
      <h3 className="text-[19px] font-bold leading-[1.35]">{p.title}</h3>
      {p.said ? (
        <p data-testid={p.saidTestId ?? "ask-said"} className="-mt-1.5 text-[13px] text-muted-foreground [overflow-wrap:anywhere]">
          <span className="text-subtle-foreground">{t("kit.arslanSays")}</span>{p.said}
        </p>
      ) : null}
      {p.risk ? (
        <div data-testid="ask-risk" className="flex items-center gap-2 rounded-[10px] bg-ask-soft px-3 py-2 text-[13px] font-semibold text-ask">
          <Lock size={15} aria-hidden="true" className="shrink-0" />
          <span>{p.risk}</span>
        </div>
      ) : null}
      {p.detail}
      {p.context && p.context.length > 0 && (
        <ul className="flex flex-col gap-[7px] text-[13px] text-muted-foreground">
          {p.context.map((c, i) => (
            <li key={i} className="flex items-center gap-2">{c.icon}<span>{c.text}</span></li>
          ))}
        </ul>
      )}
      {p.options}
      <div className="flex gap-2.5">
        <Button tone={p.safeDefault ? "primary" : "secondary"} grow={p.safeDefault ? 1.4 : 1} kbd="esc" disabled={p.busy}
          aria-disabled={held || undefined} onClick={() => { if (!guarded()) p.onDecline(); }} data-testid={declineId}>
          {p.declineLabel ?? t("kit.decline")}
        </Button>
        <Button tone={p.destructive ? "destructive" : "primary"} grow={p.safeDefault ? 1 : 1.4} kbd={allowKey ? "⌘⏎" : undefined}
          disabled={p.busy || p.allowDisabled} aria-disabled={held || undefined}
          onClick={() => { if (!guarded()) p.onAllow(); }} data-testid={p.allowTestId ?? "ask-allow"}>
          {p.allowLabel ?? t("kit.allow")}
        </Button>
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
