// RenameInput — the in-place editor for a conversation's name, shared by the sidebar row and the
// conversation header. Enter or leaving the field saves, Esc cancels; an empty or unchanged name keeps
// the old one (onRename is not called). The caller decides where the name goes.
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

export default function RenameInput({ value, onRename, onClose, className = "", testId }: {
  value: string;
  onRename: (title: string) => void;
  /** byKey: closed by Enter or Esc, so focus can go back to where editing started (a blur already moved it). */
  onClose: (byKey: boolean) => void;
  className?: string;
  testId?: string;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLInputElement>(null);
  // Enter, Esc and the blur that follows them must finish once: the first one decides.
  const done = useRef(false);
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  const finish = (save: boolean, byKey: boolean) => {
    if (done.current) return;
    done.current = true;
    const next = (ref.current?.value ?? "").trim();
    if (save && next && next !== value.trim()) onRename(next);
    onClose(byKey);
  };
  return <input ref={ref} type="text" defaultValue={value} aria-label={t("sidebar.renameLabel")} data-testid={testId}
    // The row and the header react to clicks and keys; typing in here is not one of them.
    onClick={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}
    onKeyDown={(event) => {
      event.stopPropagation();
      // Enter that confirms an IME candidate (Chinese, Japanese input) is not "save".
      if (event.nativeEvent.isComposing || event.keyCode === 229) return;
      if (event.key === "Enter") { event.preventDefault(); finish(true, true); }
      else if (event.key === "Escape") { event.preventDefault(); finish(false, true); }
    }}
    onBlur={() => finish(true, false)}
    className={`min-w-0 flex-1 rounded-md border border-primary bg-surface px-1.5 py-0.5 text-foreground outline-none ring-[3px] ring-primary/45 ${className}`} />;
}
