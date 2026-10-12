import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { appleScriptRisk } from "../../lib/scriptRisk";

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
  return (
    <label className="flex items-start gap-2 text-[13px] text-muted-foreground">
      <input type="checkbox" data-testid={testId} checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="mt-[3px] accent-foreground" />
      <span>{label}</span>
    </label>
  );
}

/** 0.1.61 §A4: the only scope ids a card answers with. */
export const SCOPES = ["once", "task", "conversation", "always"] as const;

/** The choices a card shows: the frame's own options, in its order, known ids only, and
 *  "always" only with its literal scope (a bare "Always" would not say what it allows). */
export function visibleScopes(options: string[] | undefined, alwaysLabel?: string): string[] {
  return (options ?? []).filter((o) => (SCOPES as readonly string[]).includes(o) && (o !== "always" || !!alwaysLabel));
}

/** What a yes is sent with: the choice when the card shows it, else the card's first option. */
export function scopeToSend(options: string[] | undefined, chosen: string | undefined, alwaysLabel?: string): string | undefined {
  const shown = visibleScopes(options, alwaysLabel);
  if (!shown.length) return undefined;
  return chosen && shown.includes(chosen) ? chosen : shown[0];
}

/** 0.1.61 §A4: how long a yes lasts — exactly the choices the card offers, the first chosen by
 *  the caller. One choice (or none) needs no picker, so nothing is drawn. */
export function ScopeChoice({ options, value, onChange, alwaysLabel, testId = "ask-scope" }: {
  options: string[] | undefined; value: string; onChange: (v: string) => void; alwaysLabel?: string; testId?: string;
}) {
  const { t } = useTranslation();
  const name = useId();
  const shown = visibleScopes(options, alwaysLabel);
  if (shown.length < 2) return null;
  return (
    <div role="radiogroup" aria-label={t("kit.scope.label")} data-testid={testId} className="flex flex-col gap-1.5">
      {shown.map((o) => (
        <label key={o} className="flex items-start gap-2 text-[13px] text-muted-foreground">
          <input type="radio" name={name} value={o} checked={value === o} onChange={() => onChange(o)}
            data-testid={`${testId}-${o}`} className="mt-[3px] accent-foreground" />
          <span>{o === "always" ? t("kit.scope.always", { label: alwaysLabel ?? "" }) : t(`kit.scope.${o}`)}</span>
        </label>
      ))}
    </div>
  );
}

/**
 * "No — tell Arslan what to do instead" (0.1.61 §A4): a link that opens one optional line.
 * A plain No stays the card's own button. The line owns its keys, so nothing typed in it is lost
 * or turned into a yes: ⏎ or ⌘⏎ says No with the note; esc closes the line and keeps the text.
 */
export function DeclineNote({ onDeclineWithNote, testId = "ask-note" }: {
  onDeclineWithNote: (note: string) => void; testId?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const link = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !open) link.current?.focus();    // back where the user was
    wasOpen.current = open;
  }, [open]);
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;      // an input method's ⏎ / esc
    if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation();                      // never the card's esc
      setOpen(false);
    } else if (e.key === "Enter") {
      e.preventDefault(); e.stopPropagation();                      // never the card's ⌘⏎
      onDeclineWithNote(note.trim());
    }
  };
  if (!open) {
    return (
      <button ref={link} type="button" data-testid={`${testId}-open`} aria-expanded={false} onClick={() => setOpen(true)}
        className="mx-auto text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
        {t("kit.noteLink")}
      </button>
    );
  }
  return (
    <form data-testid={testId} className="flex gap-2" onSubmit={(e) => { e.preventDefault(); onDeclineWithNote(note.trim()); }}>
      <input autoFocus value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={onKey} maxLength={500}
        aria-label={t("kit.notePlaceholder")} placeholder={t("kit.notePlaceholder")} data-testid={`${testId}-input`}
        className="min-w-0 flex-1 rounded-lg border border-border bg-surface-raised px-2.5 py-1.5 text-[13px]" />
      <button type="submit" data-testid={`${testId}-send`} className="rounded-lg border border-border px-3 text-[13px]">
        {t("kit.noteSend")}
      </button>
    </form>
  );
}
