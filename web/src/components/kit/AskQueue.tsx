import { Fragment, useEffect, useLayoutEffect, useRef, useState, type ReactElement } from "react";
import type { AskQueuePosition } from "./AskCard";
import { AnswerGuardScope, useQueueGuard } from "./guard";

/**
 * Several pending asks shown as ONE card with "‹ 1 / 3 ›" (0.1.55). Before, every
 * card rendered into the same absolute slot and two waiting at once overlapped.
 * `items` are render functions so each card gets its queue position; when the
 * shown card is answered (it leaves `items`), the next one moves up.
 */
export interface QueuedAsk { key: string; render: (queue: AskQueuePosition) => ReactElement }

export function AskQueue({ items }: { items: QueuedAsk[] }) {
  const [shown, setShown] = useState<string | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const refocus = useRef<string | null>(null);
  const index = Math.max(0, items.findIndex((i) => i.key === shown));
  // 0.1.63: from the current value, not this render's: an effect that runs late (after a page turn) must not
  // see the old `shown` and put the first card back (askqueue-late-effect.test.tsx).
  useEffect(() => {
    if (items.length) setShown((cur) => (items.some((i) => i.key === cur) ? cur : items[0].key));
  }, [items]);
  // The re-mount below replaces the ‹ › that was just pressed: if it had focus, the same button on the new
  // card gets it before paint, so paging from the keyboard does not fall back to <body>.
  useLayoutEffect(() => {
    const nav = refocus.current;
    refocus.current = null;
    if (nav) host.current?.querySelector<HTMLElement>(`[data-nav="${nav}"]`)?.focus();
  }, [shown]);
  // The card on top changed (the one before it was answered, resolved elsewhere, ran out or paged away, or the queue itself is gone, or
  // a card came up where none was): for ANSWER_GUARD_MS nothing answers the card that comes up, so a double-click or a second ⌘⏎ aimed
  // at the one that left — or a click aimed at what was there before the slot opened — never lands, unread, on the card now there
  // (see guard.ts). Only the same card sent again is no change.
  const guard = useQueueGuard();
  const top = items.length ? items[Math.min(index, items.length - 1)].key : null;
  useLayoutEffect(() => { guard.shown(top); }, [guard, top]);
  useLayoutEffect(() => () => guard.shown(null), [guard]);
  if (!items.length) return null;
  const at = Math.min(index, items.length - 1);
  const go = (n: number) => {
    const held = document.activeElement;
    refocus.current = held instanceof HTMLElement && host.current?.contains(held) ? held.dataset.nav ?? null : null;
    setShown(items[(n + items.length) % items.length].key);
  };
  const queue: AskQueuePosition = {
    index: at, total: items.length,
    onPrev: items.length > 1 ? () => go(at - 1) : undefined,
    onNext: items.length > 1 ? () => go(at + 1) : undefined,
  };
  // Keyed by the ask: two cards of one kind are one component, so without it ‹ › would carry what the
  // person typed or ticked on the first (an opened note and its text) to the next.
  return (
    <AnswerGuardScope value={guard}>
      <div ref={host} data-testid="ask-queue-host" className="flex w-full justify-center">
        <Fragment key={items[at].key}>{items[at].render(queue)}</Fragment>
      </div>
    </AnswerGuardScope>
  );
}
