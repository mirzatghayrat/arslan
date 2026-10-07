import { useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * The folded detail inside an asking card (0.1.55): code, a command, a path.
 * Line numbers, mono; the first `fold` lines shown, the rest behind "show all".
 * `marks` highlights the words the code-derived risk line points at.
 */
export function CodeBox({ code, fold = 6, numbered = true, marks = [] }:
  { code: string; fold?: number; numbered?: boolean; marks?: string[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const lines = code.replace(/\s+$/, "").split("\n");
  const shown = open ? lines : lines.slice(0, fold);
  const mark = (line: string) => {
    if (!marks.length) return line;
    const re = new RegExp(`(${marks.map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
    return line.split(re).map((part, i) => (i % 2 ? <span key={i} className="text-ask">{part}</span> : part));
  };
  return (
    <div data-testid="ask-code" className="max-h-64 overflow-auto rounded-[10px] bg-surface-raised px-3 py-2.5 font-mono text-[12px] leading-[19px] text-muted-foreground">
      {shown.map((line, i) => (
        <div key={i} className="whitespace-pre-wrap break-all">
          {numbered && <span className="mr-3 select-none text-subtle-foreground">{i + 1}</span>}
          {mark(line)}
        </div>
      ))}
      {lines.length > fold && (
        <button type="button" onClick={() => setOpen(!open)}
          className="mt-1.5 font-sans text-[12px] text-subtle-foreground hover:text-foreground">
          {open ? t("kit.showLess") : t("kit.showAll", { count: lines.length })} ›
        </button>
      )}
    </div>
  );
}
