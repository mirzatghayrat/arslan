import type { ReactNode } from "react";

/**
 * ProposalRow (0.1.55): one look for "Arslan wants to remember / learned / noticed …"
 * everywhere — the learned line, the noticed-earlier banner, memory proposals, the
 * curation inbox, learned practices. Behaviour and APIs stay with the caller.
 */
export function ProposalRow({ text, meta, actions, waiting = false, testId = "proposal-row" }: {
  text: ReactNode; meta?: ReactNode; actions?: ReactNode; waiting?: boolean; testId?: string;
}) {
  return (
    <div data-testid={testId} className={`flex items-center gap-3 px-4 py-2.5 ${waiting ? "bg-ask-soft" : ""}`}>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-[14px] leading-snug text-foreground">{text}</span>
        {meta ? <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-subtle-foreground">{meta}</span> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}

/** A small pill used in row metadata: kind, scope, "仅本机". */
export function Tag({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "info" | "danger" | "ask" }) {
  const c = { plain: "bg-fill text-muted-foreground", info: "bg-info-soft text-info-strong",
    danger: "bg-danger-soft text-danger-strong", ask: "bg-ask-soft text-ask" }[tone];
  return <span className={`whitespace-nowrap rounded-full px-[7px] py-0.5 text-[11px] ${c}`}>{children}</span>;
}
