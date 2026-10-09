import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import RunReplay from "../RunReplay";

/**
 * A run opened from Activity (0.1.58 §7): a drawer from the right over the page, so the
 * list underneath keeps its place and its highlighted row. Esc closes; ↑/↓ step through
 * the list while it is open (not while typing in a field).
 */
export default function RunDrawer({ runId, onClose, onStep }: {
  runId: number; onClose: () => void; onStep?: (delta: -1 | 1) => void;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      else if (onStep && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        onStep(e.key === "ArrowDown" ? 1 : -1);
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose, onStep]);
  return (
    <aside role="dialog" aria-label={t("activityPage.run", { id: runId })} data-testid="run-drawer"
      className="fixed inset-y-0 right-0 z-40 flex w-[min(880px,70vw)] flex-col border-l border-border bg-background shadow-2xl">
      <div className="flex-1 overflow-auto p-5">
        <RunReplay key={runId} runId={runId} onClose={onClose} />
      </div>
      <div className="flex justify-between border-t border-border px-5 py-2 text-[11px] text-subtle-foreground">
        <span>{t("activityPage.drawerKeys")}</span>
      </div>
    </aside>
  );
}
