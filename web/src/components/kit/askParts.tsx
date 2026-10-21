import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { appleScriptRisk } from "../../lib/scriptRisk";
import { useAnswerGuard } from "./guard";

/** A context line's icon, sized like the mock (15px, secondary label colour). */
export const lineIcon = (Icon: (p: { className?: string; "aria-hidden"?: boolean }) => ReactNode) =>
  <Icon className="h-[15px] w-[15px] shrink-0" aria-hidden />;

/** "这段脚本会删除东西（第 2 行：delete）· 以代码为准", from the code, or null when it only reads. */
export function scriptRiskLine(code: string, t: TFunction): string | null {
  const r = appleScriptRisk(code);
  if (!r) return null;
  if (!r.effects.length) return t("kit.riskUnknown");
  return t("kit.riskLine", {
    what: r.effects.map((e) => t(`kit.risk.${e}`)).join(t("kit.riskJoin")),
    lines: r.lines.join(", "), words: r.words.join(", "),
  });
}

/** Fingerprints of another machine, for a person to compare against the machine itself. */
export function Fingerprints({ label, list, testId }: { label: string; list: string[]; testId: string }) {
  if (!list.length) return null;
  return (
    <div data-testid={testId} className="flex flex-col gap-1 rounded-[10px] bg-surface-raised px-3 py-2.5">
      <span className="text-[12px] text-muted-foreground">{label}</span>
      {list.map((fp) => <code key={fp} className="break-all font-mono text-[11.5px] text-foreground">{fp}</code>)}
    </div>
  );
}

/** A checkbox option under the card ("don't ask again …"). */
export function AskOption({ checked, onChange, label, testId }:
  { checked: boolean; onChange: (v: boolean) => void; label: string; testId: string }) {
  const guarded = useAnswerGuard();                           // a tick right after the card came up in a queue is not for it
  return (
    <label className="flex items-start gap-2 text-[13px] text-muted-foreground">
      <input type="checkbox" data-testid={testId} checked={checked} onChange={(e) => { if (!guarded()) onChange(e.target.checked); }}
        className="mt-[3px] accent-foreground" />
      <span>{label}</span>
    </label>
  );
}

/** 0.1.61 §A4: the only scope ids a card answers with. */
export const SCOPES = ["once", "task", "conversation", "always"] as const;

/** The choices a card shows: the frame's own options, in its order, known ids only, each once, and
 *  "always" only with its literal scope (a bare "Always" would not say what it allows). */
export function visibleScopes(options: string[] | undefined, alwaysLabel?: string): string[] {
  const hasLabel = !!alwaysLabel?.trim();                       // a label of spaces says nothing
  const shown: string[] = [];
  for (const o of options ?? []) {
    if (!(SCOPES as readonly string[]).includes(o) || shown.includes(o)) continue;     // unknown, or repeated
    if (o === "always" && !hasLabel) continue;
    shown.push(o);
  }
  return shown;
}

/** What a yes is sent with: the choice when the card shows it, else the card's first SHOWN option
 *  that is not "always". Always is sent only when the person picked it: never as a default. */
export function scopeToSend(options: string[] | undefined, chosen: string | undefined, alwaysLabel?: string): string | undefined {
  const shown = visibleScopes(options, alwaysLabel);
  if (chosen && shown.includes(chosen)) return chosen;
  return shown.find((o) => o !== "always");
}

/** 0.1.61 (plan R14): the permission kinds whose Allow is drawn red — the step pays, or cannot be
 *  undone. The one definition, for every card that carries the frame's `perm_kind`; the names are
 *  checked against the server's `permissions.KINDS` by tests/server/test_card_kinds.py. */
export const RED_KINDS = new Set(["money", "app_risky", "destructive"]);

/** The kinds a card answers for this one time only. Mirrors the server's `permissions._ONCE_ONLY`; keep the
 *  two in step (plan R14: tests/server/test_card_kinds.py is where the web's kind names meet the server's). */
export const ONCE_ONLY_KINDS = new Set(["money", "app_risky", "capability", "other_agent", "system", "opaque", "remote", "takeover"]);

/** The kinds whose card is answered only where its whole card is shown (0.1.57: installing code wants the whole card): the server swallows the
 *  phone's yes and refuses the Inbox's and the island's for a card of one of these, whatever type of frame carries it (`approvals.window_only`),
 *  so the Inbox draws "Open in Arslan" for it instead of Allow. Keep it equal to the server's `approvals.WINDOW_ONLY_KINDS`
 *  (tests/server/test_card_kinds.py). */
export const WINDOW_ONLY_KINDS = new Set(["capability"]);

/** S1: the kinds whose card starts on "In this conversation" in the window: an MCP tool is usually used again
 *  in the same conversation. Only the window's starting choice: the options' order is the server's, and the island
 *  and the phone still answer the first ("this time"). Checked against the server's kinds by
 *  tests/server/test_card_kinds.py. */
export const CONVERSATION_FIRST_KINDS = new Set(["mcp_tool"]);

/** The choices a card is willing to offer. For a once-only kind that is the frame's first alone,
 *  whatever else it lists: the server already clamps, so this only keeps a mistaken frame from
 *  drawing — or sending — a longer yes than the kind allows. */
export function offeredScopes(options: string[] | undefined, permKind?: string): string[] | undefined {
  return permKind && ONCE_ONLY_KINDS.has(permKind) ? options?.slice(0, 1) : options;
}

/** 0.1.61 §A4: how long a yes lasts — exactly the choices the card offers. What is ticked is what a
 *  yes will send (`scopeToSend`), so a value the card does not show ticks its default. One choice
 *  (or none) needs no picker, so nothing is drawn — except Always, which is drawn even alone: it
 *  is only ever sent by being picked where the person can see it. */
export function ScopeChoice({ options, value, onChange, alwaysLabel, conversationLabel, testId = "ask-scope" }: {
  options: string[] | undefined; value: string; onChange: (v: string) => void; alwaysLabel?: string;
  /** What "In this conversation" covers when that is more than the request on the card (every command of its kind, any
   *  scheduled task, any file in the folder): said on the choice, as "Always" says its literal scope. */
  conversationLabel?: string; testId?: string;
}) {
  const { t } = useTranslation();
  const name = useId();
  const guarded = useAnswerGuard();                           // a pick right after the card came up in a queue is not for it
  const shown = visibleScopes(options, alwaysLabel);
  if (shown.length < 2 && !shown.includes("always")) return null;
  const ticked = scopeToSend(options, value, alwaysLabel);
  return (
    <div role="radiogroup" aria-label={t("kit.scope.label")} data-testid={testId} className="flex flex-col gap-1.5">
      {shown.map((o) => (
        <label key={o} className="flex items-start gap-2 text-[13px] text-muted-foreground">
          <input type="radio" name={name} value={o} checked={ticked === o} onChange={() => { if (!guarded()) onChange(o); }}
            data-testid={`${testId}-${o}`} className="mt-[3px] accent-foreground" />
          <span>{o === "always" ? t("kit.scope.always", { label: alwaysLabel?.trim() ?? "" })
            : o === "conversation" && conversationLabel?.trim() ? t("kit.scope.conversationFor", { label: conversationLabel.trim() })
            : t(`kit.scope.${o}`)}</span>
        </label>
      ))}
    </div>
  );
}

/**
 * 0.1.61 §A4: while a card's own apply is in flight (connecting a server, enrolling a machine) its Allow, No and keys are off, and a REST call
 * has no client timeout. This is the way out that is not an answer: the apply goes on, the card leaves, and the chat says how it ended.
 */
export function HideWhileBusy({ onHide, testId }: { onHide: () => void; testId: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center gap-0.5 text-center">
      <button type="button" data-testid={testId} onClick={onHide}
        className="text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
        {t("kit.hide")}
      </button>
      <span className="text-[12px] text-subtle-foreground">{t("kit.hideHint")}</span>
    </div>
  );
}

/**
 * "No — tell Arslan what to do instead" (0.1.61 §A4): a link that opens one optional line.
 * A plain No stays the card's own button. The line owns its keys (the input's and its Say no button's),
 * so nothing typed in it is lost or turned into a yes: ⏎ or ⌘⏎ says No with the note; esc closes the
 * line and keeps the text. `disabled` (a card that is already busy answering) sends nothing.
 */
export function DeclineNote({ onDeclineWithNote, disabled = false, testId = "ask-note" }: {
  onDeclineWithNote: (note: string) => void; disabled?: boolean; testId?: string;
}) {
  const { t } = useTranslation();
  const guarded = useAnswerGuard();                           // a note sent right after its card came up in a queue is not for it
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const link = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !open) link.current?.focus();    // back where the user was
    wasOpen.current = open;
  }, [open]);
  const send = () => { if (!disabled && !guarded()) onDeclineWithNote(note.trim()); };
  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;      // an input method's ⏎ / esc
    if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation();                      // never the card's esc
      setOpen(false);
    } else if (e.key === "Enter") {
      e.preventDefault(); e.stopPropagation();                      // never the card's ⌘⏎
      if (!e.repeat) send();      // a held ⏎ says No once; its repeats are cancelled too, or the form would submit on each
    }
  };
  if (!open) {
    return (
      <button ref={link} type="button" data-testid={`${testId}-open`} onClick={() => setOpen(true)}
        className="mx-auto text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
        {t("kit.noteLink")}
      </button>
    );
  }
  return (
    <form data-testid={testId} className="flex gap-2" onKeyDown={onKey} onSubmit={(e) => { e.preventDefault(); send(); }}>
      <input autoFocus value={note} onChange={(e) => setNote(e.target.value)} maxLength={500}
        aria-label={t("kit.notePlaceholder")} placeholder={t("kit.notePlaceholder")} data-testid={`${testId}-input`}
        className="min-w-0 flex-1 rounded-lg border border-border bg-surface-raised px-2.5 py-1.5 text-[13px]" />
      <button type="submit" disabled={disabled} data-testid={`${testId}-send`}
        className="rounded-lg border border-border px-3 text-[13px] disabled:opacity-40">
        {t("kit.noteSend")}
      </button>
    </form>
  );
}
