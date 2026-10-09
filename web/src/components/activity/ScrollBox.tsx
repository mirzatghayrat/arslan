import { useLayoutEffect, useRef, type ReactNode } from "react";
import { useActivityStore } from "../../stores/activityStore";

/** How close to the end (px) counts as "reached the end" for loading the next page. */
const END_SLACK = 48;

/**
 * One Activity list in its own box (0.1.58 §7): about ten rows tall, scrolling inside
 * instead of making the page long. It remembers where it was scrolled (by `scrollKey`)
 * and calls `onEnd` when the reader reaches the bottom, which loads the next 20.
 */
export default function ScrollBox({ scrollKey, onEnd, children, testId }: {
  scrollKey: string; onEnd?: () => void; children: ReactNode; testId?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const saved = useActivityStore((s) => s.scroll[scrollKey] ?? 0);
  const saveScroll = useActivityStore((s) => s.saveScroll);
  useLayoutEffect(() => {
    if (ref.current && saved) ref.current.scrollTop = saved;
    // Only on mount: afterwards the box is the source of truth.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div ref={ref} data-testid={testId} data-scroll-key={scrollKey}
      className="max-h-[400px] overflow-y-auto rounded-lg border border-border bg-surface/40"
      onScroll={(e) => {
        const el = e.currentTarget;
        saveScroll(scrollKey, el.scrollTop);
        if (onEnd && el.scrollTop + el.clientHeight >= el.scrollHeight - END_SLACK) onEnd();
      }}>
      {children}
    </div>
  );
}
