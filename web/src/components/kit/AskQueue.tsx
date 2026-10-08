import { useEffect, useState, type ReactElement } from "react";
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
  const index = Math.max(0, items.findIndex((i) => i.key === shown));
  useEffect(() => {
    if (items.length && !items.some((i) => i.key === shown)) setShown(items[0].key);
  }, [items, shown]);
  if (!items.length) return null;
  const at = Math.min(index, items.length - 1);
  const go = (n: number) => setShown(items[(n + items.length) % items.length].key);
  const queue: AskQueuePosition = {
    index: at, total: items.length,
    onPrev: items.length > 1 ? () => go(at - 1) : undefined,
    onNext: items.length > 1 ? () => go(at + 1) : undefined,
  };
  return <div data-testid="ask-queue-host" className="flex w-full justify-center">{items[at].render(queue)}</div>;
}
