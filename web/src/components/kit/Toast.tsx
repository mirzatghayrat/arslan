import { useEffect } from "react";
import { create } from "zustand";

export interface ToastItem { id: number; text: string; action?: { label: string; onClick: () => void }; ms: number }

const useToasts = create<{ items: ToastItem[] }>(() => ({ items: [] }));
let seq = 0;

/**
 * One toast stack, bottom centre (0.1.55): replaces the App toast, the Brain status
 * toast and the update pill's own. `action` is for Undo ("已删除这条做法 · 撤销").
 */
export function toast(text: string, opts: { action?: ToastItem["action"]; ms?: number } = {}): number {
  const id = ++seq;
  const ms = opts.ms ?? (opts.action ? 6000 : 3500);
  useToasts.setState((s) => ({ items: [...s.items.slice(-2), { id, text, action: opts.action, ms }] }));
  return id;
}

export function dismissToast(id: number) {
  useToasts.setState((s) => ({ items: s.items.filter((t) => t.id !== id) }));
}

function One({ item }: { item: ToastItem }) {
  useEffect(() => {
    const timer = window.setTimeout(() => dismissToast(item.id), item.ms);
    return () => window.clearTimeout(timer);
  }, [item.id, item.ms]);
  return (
    <div role="status" data-testid="kit-toast"
      className="pointer-events-auto inline-flex h-11 items-center gap-3.5 rounded-full bg-toast pl-4 pr-2 text-[13px] text-toast-foreground shadow-kit">
      <span className="max-w-[60vw] truncate">{item.text}</span>
      {item.action ? (
        <button type="button" data-testid="kit-toast-action"
          onClick={() => { item.action?.onClick(); dismissToast(item.id); }}
          className="h-[30px] rounded-full bg-toast-foreground/15 px-3 font-semibold">
          {item.action.label}
        </button>
      ) : <span className="w-1" />}
    </div>
  );
}

/** Mounted once (App). */
export function ToastHost() {
  const items = useToasts((s) => s.items);
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-6 z-[250] flex flex-col items-center gap-2">
      {items.map((item) => <One key={item.id} item={item} />)}
    </div>
  );
}

/**
 * Delete with Undo instead of a confirm (0.1.55, for small reversible-looking things such
 * as a saved candidate): the row leaves at once, a toast offers Undo, and only when the
 * toast runs out is the delete actually sent. A failed delete puts the row back.
 */
export function deleteWithUndo(o: {
  text: string; undoLabel: string; hide: () => void; restore: () => void; commit: () => Promise<unknown>; ms?: number;
}) {
  const ms = o.ms ?? 6000;
  let undone = false;
  o.hide();
  toast(o.text, { action: { label: o.undoLabel, onClick: () => { undone = true; o.restore(); } }, ms });
  window.setTimeout(() => { if (!undone) void o.commit().catch(() => o.restore()); }, ms);
}
