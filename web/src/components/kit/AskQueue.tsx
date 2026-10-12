import { Fragment, useEffect, useLayoutEffect, useRef, useState, type ReactElement } from "react";
import type { AskQueuePosition } from "./AskCard";

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
  useEffect(() => {
    if (items.length && !items.some((i) => i.key === shown)) setShown(items[0].key);
  }, [items, shown]);
  // The re-mount below replaces the ‹ › that was just pressed: if it had focus, the same button on the new
  // card gets it before paint, so paging from the keyboard does not fall back to <body>.
  useLayoutEffect(() => {
    const nav = refocus.current;
    refocus.current = null;
    if (nav) host.current?.querySelector<HTMLElement>(`[data-nav="${nav}"]`)?.focus();
  }, [shown]);
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
    <div ref={host} data-testid="ask-queue-host" className="flex w-full justify-center">
      <Fragment key={items[at].key}>{items[at].render(queue)}</Fragment>
    </div>
  );
}
