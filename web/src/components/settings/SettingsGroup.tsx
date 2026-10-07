import type { ReactNode } from "react";

/** 0.1.55 §11: a titled group of settings rows on one surface (the mock's grouped look). */
export function SettingsGroup({ title, note, children, testId }: { title?: ReactNode; note?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <section data-testid={testId} className="flex flex-col gap-1.5">
      {title ? <h3 className="px-1 text-[12px] font-semibold text-muted-foreground">{title}</h3> : null}
      <div className="settings-group rounded-xl border border-border bg-surface px-4 py-4">{children}</div>
      {note ? <p className="px-1 text-[12px] text-subtle-foreground">{note}</p> : null}
    </section>
  );
}

/** The top of a section: its name and the one sentence of what lives there. */
export function SectionIntro({ title, hint }: { title: string; hint: string }) {
  return (
    <header className="flex flex-col gap-1">
      <h2 className="text-[22px] font-bold text-foreground">{title}</h2>
      <p className="max-w-2xl text-[13px] text-muted-foreground">{hint}</p>
    </header>
  );
}
