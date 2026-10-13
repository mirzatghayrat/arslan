import { createContext, useContext, useRef, useState, useSyncExternalStore } from "react";

/** 0.1.61 §A4: how long after the card on top of an AskQueue leaves — the one before it was answered, resolved elsewhere, ran out
 *  or was paged away — nothing can answer the one that comes up. A double-click, or a second ⌘⏎, aimed at the card that just left must
 *  never land, unread, on the one that moved up under the pointer (a double-click confirmed `echo harmless` and `rm -rf ~/Documents`),
 *  nor on one that comes up a moment later in the slot it left empty (the next command of a turn is proposed as soon as the first ran). */
export const ANSWER_GUARD_MS = 500;

/** What remembers which card is on top, and that a card has just left it. */
export interface AnswerGuardState {
  /** The card now on top (its key), or null when there is none. */
  shown(key: string | null): void;
  /** Whether an answer must be ignored right now. */
  held(): boolean;
  /** Told when the hold starts and when it ends, so the cards can show it. Returns the way to stop being told. */
  subscribe(listener: () => void): () => void;
}

/** A clock that never goes back. The wall clock can (the system corrects it, the Mac wakes), and a guard that went by it would hold every
 *  answer until the wall clock had caught up. */
const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

export function makeAnswerGuard(): AnswerGuardState {
  let top: string | null = null;
  let until = 0;
  let ends: ReturnType<typeof setTimeout> | undefined;
  const listeners = new Set<() => void>();
  const tell = () => listeners.forEach((listener) => listener());
  // The end of the hold. A timer may fire a hair before the clock says the time is up: then it waits the hair out, so a card is never left looking held.
  const finish = () => {
    const left = until - now();
    if (left > 0) ends = setTimeout(finish, left + 1);
    else tell();
  };
  return {
    shown(key) {
      // A card left (a different one, or none, is on top now): the one that comes up now, or in a moment, is held. The same card
      // again, and the first card after the slot has been empty a while, are not a change.
      if (top !== null && key !== top) {
        until = now() + ANSWER_GUARD_MS;
        clearTimeout(ends);
        ends = setTimeout(finish, ANSWER_GUARD_MS);
        tell();
      }
      top = key;
    },
    held: () => now() < until,
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}

const NEVER: AnswerGuardState = { shown: () => {}, held: () => false, subscribe: () => () => {} };
const GuardContext = createContext<AnswerGuardState | null>(null);

/** Provides a guard to the queues and cards below it. The owner of a slot that is empty between cards (AskSlot, the Inbox) provides one
 *  above its queue, which is not on screen while nothing waits and so could not remember that a card has just left. */
export const AnswerGuardScope = GuardContext.Provider;

/** A guard of one's own, for whoever provides a scope. */
export const useAnswerGuardState = (): AnswerGuardState => useState(makeAnswerGuard)[0];

/** For an AskQueue: the guard of the scope above it, or, with none, one of its own — built only then, once, and kept. */
export function useQueueGuard(build: () => AnswerGuardState = makeAnswerGuard): AnswerGuardState {
  const above = useContext(GuardContext);
  const own = useRef<AnswerGuardState | null>(null);
  if (above) return above;
  return (own.current ??= build());
}

/** For a card's doors: whether an answer (a click on Allow, No or a scope, ⌘⏎, Esc, a note) must be ignored right now. Outside a queue it never is. */
export function useAnswerGuard(): () => boolean {
  const guard = useContext(GuardContext);
  return guard ? guard.held : NEVER.held;
}

/** For a card's looks: whether the hold is on, so Allow and No can show it. It starts and ends on its own. */
export function useAnswerHeld(): boolean {
  const guard = useContext(GuardContext) ?? NEVER;
  return useSyncExternalStore(guard.subscribe, guard.held, guard.held);
}
