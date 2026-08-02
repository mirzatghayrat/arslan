import { useEffect, useRef, type RefObject } from "react";

/**
 * Outside-click and Escape dismissal for anything that floats over the page.
 *
 * WHY A HOOK AND NOT ANOTHER BACKDROP DIV: six components hand-rolled a
 * `fixed inset-0` click-away layer and three others listened for Escape, with
 * almost no overlap — so every floating thing had one half of the behaviour and
 * a different half missing. The sidebar's thread menu is where a user finally
 * hit it: measured, its backdrop closed the menu when the BACKDROP itself was
 * clicked, and a click anywhere else did nothing.
 *
 * 🔴 A backdrop is dismissal implemented as LAYOUT, and layout is exactly what
 * goes wrong here. `fixed inset-0` stops covering the viewport the moment any
 * ancestor establishes a containing block (`transform`, `filter`,
 * `backdrop-filter`, `will-change`, `contain`), and its z-index only orders it
 * within its own stacking context — anything painted in a sibling context sits
 * on top and swallows the click. A document-level listener has no geometry and
 * no stacking, so none of that reasoning applies.
 *
 * TWO refs, not one, because the floating element is usually PORTALLED and so
 * is not a DOM descendant of its trigger. A click in either is "inside".
 *
 * `mousedown`, not `click`: it fires before focus moves, and a drag that starts
 * inside the menu and ends outside does not count as leaving.
 */
export function useDismissable<A extends HTMLElement, F extends HTMLElement>(
  open: boolean,
  onClose: () => void,
): { anchorRef: RefObject<A | null>; floatingRef: RefObject<F | null> } {
  const anchorRef = useRef<A | null>(null);
  const floatingRef = useRef<F | null>(null);
  // Kept in a ref so the effect does not re-subscribe on every render when the
  // caller passes an inline arrow — a re-subscribe between mousedown and click
  // is how these listeners end up missing events.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;

    const inside = (target: EventTarget | null) =>
      (target instanceof Node) &&
      (Boolean(anchorRef.current?.contains(target)) ||
       Boolean(floatingRef.current?.contains(target)));

    const onPointer = (e: MouseEvent | TouchEvent) => {
      if (!inside(e.target)) onCloseRef.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
      }
    };

    document.addEventListener("mousedown", onPointer);
    document.addEventListener("touchstart", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("touchstart", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return { anchorRef, floatingRef };
}
