import { useCallback, useEffect, useRef, type PointerEvent } from "react";

const PROPS = ["user-select", "-webkit-user-select"] as const;

/**
 * Pointer handlers for a panel divider (the workbench's and the work dock's left edge).
 *
 * WHY: pointer capture alone does not stop the browser's own text selection. The pointerdown's
 * default (the mousedown it turns into) starts a selection, and the drag then extends it across the
 * conversation and the panel. So the pointerdown cancels its default, clears any selection already
 * there, and the body gets `user-select: none` (and the WebKit-prefixed form, for the macOS web view)
 * for the drag. The body's own values come back on pointerup, pointercancel, lost capture, and when
 * the divider goes away mid-drag: `shown` turning false (the panel closes but stays mounted) or unmount.
 */
export function useDividerDrag(shown: boolean, onMove: (clientX: number) => void) {
  const saved = useRef<string[] | null>(null);
  const end = useCallback(() => {
    if (!saved.current) return;
    const style = document.body.style;
    PROPS.forEach((prop, i) => { if (saved.current![i]) style.setProperty(prop, saved.current![i]); else style.removeProperty(prop); });
    saved.current = null;
  }, []);
  useEffect(() => (shown ? end : undefined), [shown, end]);
  return {
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      e.preventDefault();
      window.getSelection()?.removeAllRanges();
      e.currentTarget.setPointerCapture(e.pointerId);
      const style = document.body.style;
      if (!saved.current) saved.current = PROPS.map((prop) => style.getPropertyValue(prop));
      PROPS.forEach((prop) => style.setProperty(prop, "none"));
    },
    onPointerMove: (e: PointerEvent<HTMLElement>) => { if (e.currentTarget.hasPointerCapture(e.pointerId)) onMove(e.clientX); },
    onPointerUp: (e: PointerEvent<HTMLElement>) => {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
      end();
    },
    onPointerCancel: end,
    onLostPointerCapture: end,
  };
}
