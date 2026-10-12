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

/** A field the user types words into (not a checkbox, a radio or a button). */
function typingField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLTextAreaElement) return true;
  if (target instanceof HTMLInputElement) {
    return !["checkbox", "radio", "button", "submit", "reset", "range", "color", "file"].includes(target.type);
  }
  return target.closest('[contenteditable=""], [contenteditable="true"], [contenteditable="plaintext-only"], [role="textbox"]') !== null;
}

/** Another card or dialog: a surface with keys of its own. */
const SURFACE = '[role="alertdialog"], [role="dialog"]';

/**
 * ⌘⏎ (Ctrl+⏎ elsewhere) allows, Esc declines — user decision 2, 2026-10-05.
 * Plain ⏎ NEVER answers: it would while typing in the composer. Keys typed during
 * an input-method composition (Chinese, Japanese) are ignored, and so is a HELD key: a
 * repeat of the press that answered one card must never answer the card that moves up.
 * 0.1.61 §A4: typing while a card waits is how the user says No, so ⌘⏎ from a text field
 * OUTSIDE the surface (the composer) never allows; a field on the surface itself (a key it
 * asks for) still does. Esc declines from anywhere, as before — except from inside ANOTHER
 * card or dialog, whose keys they are (`within` is this surface's own panel, `null` if it has
 * none). Required, so that a caller who forgets it fails tsc rather than a person.
 */
export function useAnswerKeys(enabled: boolean, { onAllow, onDecline }: KeyHandlers,
                              within: { current: HTMLElement | null } | null) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing || e.keyCode === 229 || e.repeat) return;
      const target = e.target;
      const inside = target instanceof Node && !!within?.current?.contains(target);
      if (!inside && within?.current && target instanceof Element && target.closest(SURFACE)) return;
      if (e.key === "Escape" && onDecline) {
        e.preventDefault();
        onDecline();
      } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && onAllow) {
        if (typingField(target) && !inside) return;
        e.preventDefault();
        onAllow();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, onAllow, onDecline, within]);
}
