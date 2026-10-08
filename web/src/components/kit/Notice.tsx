import type { ReactNode } from "react";

export type NoticeTone = "info" | "warn" | "error";

const TONE: Record<NoticeTone, { box: string; dot: string; title: string }> = {
  info: { box: "bg-info-soft", dot: "bg-info-strong", title: "text-info-strong" },
  warn: { box: "bg-ask-soft", dot: "bg-ask", title: "text-ask" },
  error: { box: "bg-danger-soft", dot: "bg-danger-strong", title: "text-danger-strong" },
};

/**
 * Notice (0.1.55): an inline line that never blocks — tone, a short title, one
 * sentence, optionally one action. Replaces the chat error banner, the escalation
 * banner, NoModelHint, ToolTransportWarning, CryptoHealthNotice and ~60 one-off
 * alert lines.
 */
export function Notice({ tone = "info", title, children, action, testId = "kit-notice", className = "", role, attrs }: {
  tone?: NoticeTone; title?: ReactNode; children?: ReactNode; action?: ReactNode; testId?: string; className?: string;
  /** A standing property (not an event) is "status" even when it is bad news. */
  role?: "alert" | "status";
  attrs?: Record<string, string>;
}) {
  const c = TONE[tone];
  return (
    <div data-testid={testId} data-tone={tone} role={role ?? (tone === "error" ? "alert" : "status")} {...attrs}
      className={`flex items-center gap-3 rounded-xl px-3.5 py-3 ${c.box} ${className}`}>
      <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${c.dot}`} />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {title ? <span className={`text-[13px] font-semibold ${c.title}`}>{title}</span> : null}
        {children ? <span className="text-[13px] text-muted-foreground">{children}</span> : null}
      </div>
      {action}
    </div>
  );
}
