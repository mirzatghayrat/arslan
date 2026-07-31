import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/**
 * The shape an empty panel takes: what this is, what to do next, and a control
 * that does it.
 *
 * Gate item ②. An audit of every empty state in the app found 61 of them, of
 * which 6 had any control inside the block — the rest were dead-end text like
 * "No runs yet". "No data" is not an empty state; it is the absence of one. A
 * panel that is empty on a fresh install is the FIRST thing a new user sees of
 * that feature, so it is the worst possible place to say nothing.
 *
 * Two sizes, because the failure of a one-size component is that it gets used
 * at the wrong scale and people stop using it:
 *
 *   "panel"   a whole screen area is empty (spawn ledger, capability catalog,
 *             the brain graph). Full dashed box, centred, room for a body.
 *   "inline"  a section inside an otherwise-populated panel (a sidebar list,
 *             a card's sub-table). One line plus an optional control.
 *
 * `action` is deliberately a ReactNode rather than a label+onClick pair: some
 * of these want a button, some want a file input, and the brain wants a text
 * field. Forcing them all into a button prop is how you end up with an empty
 * state whose "next step" is not actually the next step.
 */
export default function EmptyState({
  icon: Icon,
  title,
  body,
  action,
  size = "panel",
  tone = "neutral",
  testId = "empty-state",
}: {
  icon?: LucideIcon;
  title: string;
  /** The second line. Optional for `inline`; a `panel` without one is usually
   *  a "No data" in disguise, so the tests assert panels carry one. */
  body?: string;
  action?: ReactNode;
  size?: "panel" | "inline";
  tone?: "neutral" | "danger";
  testId?: string;
}) {
  const danger = tone === "danger";

  if (size === "inline") {
    return (
      <div className="flex flex-col gap-1.5 py-2" data-testid={testId}>
        <p className={`text-[11px] font-mono ${danger ? "text-danger" : "text-subtle-foreground"}`}>
          {title}
        </p>
        {body && <p className="text-[10px] font-sans text-subtle-foreground">{body}</p>}
        {action}
      </div>
    );
  }

  return (
    <div
      data-testid={testId}
      className={`h-64 border border-dashed rounded-2xl flex flex-col items-center justify-center text-center p-6 ${
        danger ? "border-danger/40 bg-danger/10" : "border-border bg-background"
      }`}
    >
      {Icon && <Icon className={`w-8 h-8 mb-2 ${danger ? "text-danger/60" : "text-subtle-foreground"}`} />}
      <h3 className={`text-sm font-sans font-medium ${danger ? "text-danger" : "text-foreground"}`}>
        {title}
      </h3>
      {body && (
        <p className={`text-xs max-w-sm mt-1 ${danger ? "text-danger/70" : "text-subtle-foreground"}`}>
          {body}
        </p>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/** The button an empty state offers. Same vocabulary as the scheduled-tasks
 *  card header, so the control does not read as a different app's. */
export function EmptyStateAction({
  onClick,
  children,
  testId = "empty-state-action",
}: {
  onClick: () => void;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-mono text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] border border-border transition-colors"
    >
      {children}
    </button>
  );
}
