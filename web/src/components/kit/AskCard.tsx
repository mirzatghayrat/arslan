import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUpRight, Lock } from "lucide-react";
import { AskMark } from "./AskMark";
import { Button } from "./Button";
import { Countdown } from "./Countdown";
import { useAnswerKeys, useLayer } from "./layers";

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
  busy?: boolean;
  /** Only the allow answer is not possible yet (e.g. a required key is empty); esc still declines. */
  allowDisabled?: boolean;
  /** "See the whole context" (island, inbox → the conversation). */
  onOpenContext?: () => void;
  /** Extra actions beside the two answers (e.g. "run again outside the sandbox"). */
  extra?: ReactNode;
  /** Answers to ⌘⏎ / esc while it is the top surface. Off when shown as a preview. */
  keys?: boolean;
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
 * ScheduleGrantCard, EnrollNodeCard, ConnectMcpCard and the phone pairing request.
 */
export function AskCard(p: AskCardProps) {
  const { t } = useTranslation();
  const top = useLayer(p.keys !== false);
  useAnswerKeys(top && !p.busy, { onAllow: () => { if (!p.allowDisabled) p.onAllow(); }, onDecline: p.onDecline });
  return (
    <section data-testid={p.testId ?? "ask-card"} role="alertdialog" aria-label={p.who} {...p.attrs}
      className={`flex w-full max-w-[460px] flex-col gap-3.5 rounded-2xl border border-border bg-surface px-5 pb-4 pt-[18px] text-foreground shadow-kit ${p.className ?? ""}`}>
      <header className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <AskMark />
          <span className="truncate text-[13px] font-semibold text-ask">{p.who}</span>
        </div>
        <div className="flex items-center gap-2.5">
          {p.queue && p.queue.total > 1 && (
            <span data-testid="ask-queue" className="inline-flex items-center gap-1.5 font-mono text-[12px] text-muted-foreground">
              <button type="button" aria-label={t("kit.previous")} disabled={!p.queue.onPrev} onClick={p.queue.onPrev}
                className="px-0.5 hover:text-foreground disabled:opacity-40">‹</button>
              {t("kit.queueOf", { index: p.queue.index + 1, total: p.queue.total })}
              <button type="button" aria-label={t("kit.next")} disabled={!p.queue.onNext} onClick={p.queue.onNext}
                className="px-0.5 hover:text-foreground disabled:opacity-40">›</button>
            </span>
          )}
          {p.expiresAt ? <Countdown expiresAt={p.expiresAt} totalMs={p.totalMs ?? 300_000} /> : null}
        </div>
      </header>
      <h3 className="text-[19px] font-bold leading-[1.35]">{p.title}</h3>
      {p.said ? (
        <p data-testid={p.saidTestId ?? "ask-said"} className="-mt-1.5 text-[13px] text-muted-foreground">
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
        <Button tone="secondary" grow={1} kbd="esc" disabled={p.busy} onClick={p.onDecline} data-testid={p.declineTestId ?? "ask-decline"}>
          {p.declineLabel ?? t("kit.decline")}
        </Button>
        <Button tone={p.destructive ? "destructive" : "primary"} grow={1.4} kbd="⌘⏎" disabled={p.busy || p.allowDisabled}
          onClick={p.onAllow} data-testid={p.allowTestId ?? "ask-allow"}>
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
