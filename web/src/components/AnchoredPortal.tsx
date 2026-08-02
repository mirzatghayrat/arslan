import { useLayoutEffect, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

/**
 * Renders a floating element at the document root, positioned against an anchor.
 *
 * WHY: an `absolute` popover inside a scrolling list is clipped by that list.
 * The sidebar's bottom conversation row is where it showed: its "···" menu was
 * cut off by `overflow-y-auto` on the thread list. Every popover living inside
 * a scroll container has the same bug waiting; portalling to `document.body`
 * removes the clipping ancestor from the picture entirely.
 *
 * FLIPS UP near the bottom edge, because escaping the container only moves the
 * problem to the viewport: a menu anchored to the last row would otherwise hang
 * off the bottom of the window. Also clamps horizontally — a right-aligned menu
 * on a narrow window would run off the left.
 *
 * Position is measured in `useLayoutEffect` (before paint, so the menu never
 * appears in the wrong place for a frame) and re-measured on scroll and resize,
 * since a portalled element does not move with its anchor on its own.
 */
export default function AnchoredPortal({
  anchorRef,
  floatingRef,
  open,
  children,
  align = "right",
  gap = 6,
  /** Space that must remain below the anchor, or the menu flips above it. */
  flipMargin = 12,
}: {
  anchorRef: RefObject<HTMLElement | null>;
  floatingRef: RefObject<HTMLDivElement | null>;
  open: boolean;
  children: ReactNode;
  align?: "left" | "right";
  gap?: number;
  flipMargin?: number;
}) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    if (!open) { setPos(null); return; }

    const place = () => {
      const a = anchorRef.current;
      const f = floatingRef.current;
      if (!a) return;
      const r = a.getBoundingClientRect();
      // Fall back to a nominal size on the first pass: the floating element is
      // measured only once it has rendered, and a first frame with no position
      // would flash at 0,0.
      const fw = f?.offsetWidth || 208;
      const fh = f?.offsetHeight || 160;

      const below = window.innerHeight - r.bottom;
      const flip = below < fh + flipMargin && r.top > fh + flipMargin;
      const top = flip ? r.top - fh - gap : r.bottom + gap;

      let left = align === "right" ? r.right - fw : r.left;
      left = Math.max(8, Math.min(left, window.innerWidth - fw - 8));

      setPos({ top, left });
    };

    place();
    // `true` = capture, so scrolling ANY ancestor repositions it, not just the
    // window — the anchor lives inside a scrolling list.
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, anchorRef, floatingRef, align, gap, flipMargin]);

  if (!open) return null;

  return createPortal(
    <div
      ref={floatingRef}
      data-testid="anchored-portal"
      style={{
        position: "fixed",
        top: pos?.top ?? -9999,
        left: pos?.left ?? -9999,
        // Hidden until measured rather than rendered offscreen-and-visible:
        // a menu that flashes in the corner is worse than one that appears a
        // frame later.
        visibility: pos ? "visible" : "hidden",
        zIndex: 1000,
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
