import { useEffect, useId, useSyncExternalStore } from "react";

/**
 * 0.1.55 surface kit: which surface owns the keyboard.
 *
 * Every kit surface that answers to keys (an asking card, a dialog, a confirm
 * sheet) registers a layer while it is shown; only the TOP layer reacts. Without
 * this, Esc in a dialog opened over a waiting card would also decline the card.
 */
const stack: string[] = [];
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Registers a layer while `active`; returns whether it is the top one. */
export function useLayer(active = true): boolean {
  const id = useId();
  useEffect(() => {
    if (!active) return;
    stack.push(id);
    emit();
    return () => {
      const at = stack.lastIndexOf(id);
      if (at >= 0) stack.splice(at, 1);
      emit();
    };
  }, [id, active]);
  return useSyncExternalStore(subscribe, () => active && stack[stack.length - 1] === id, () => false);
}

export type KeyHandlers = { onAllow?: () => void; onDecline?: () => void };

/**
 * ⌘⏎ (Ctrl+⏎ elsewhere) allows, Esc declines — user decision 2, 2026-10-05.
 * Plain ⏎ NEVER answers: it would while typing in the composer. Keys typed during
 * an input-method composition (Chinese, Japanese) are ignored.
 */
export function useAnswerKeys(enabled: boolean, { onAllow, onDecline }: KeyHandlers) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing || e.keyCode === 229) return;
      if (e.key === "Escape" && onDecline) {
        e.preventDefault();
        onDecline();
      } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && onAllow) {
        e.preventDefault();
        onAllow();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, onAllow, onDecline]);
}
