import { useLayoutEffect, useRef, type KeyboardEvent, type RefObject } from "react";

/** The items a key can reach: the menu's menuitems that are displayed (the header's ⋯ hides one by CSS). */
function menuItems(menu: HTMLElement | null): HTMLElement[] {
  if (!menu) return [];
  return Array.from(menu.querySelectorAll<HTMLElement>('[role="menuitem"]'))
    .filter((el) => !(el as HTMLButtonElement).disabled && getComputedStyle(el).display !== "none");
}

/**
 * Keyboard for a ⋯ menu (role="menu" with role="menuitem" children), the WAI-ARIA menu button pattern:
 *  · on open, focus goes to the first item (and again when `view` changes, e.g. a submenu replaces the list);
 *  · ArrowDown / ArrowUp move between items and wrap, Home / End go to the first / last;
 *  · on any close (Esc, an item, the trigger, a click outside), focus goes back to the trigger — unless
 *    something else has already taken it (an item that opened an editor or a dialog keeps it there).
 * Esc and outside clicks themselves are useDismissable's; this only moves focus.
 * Returns the menu's onKeyDown.
 */
export function useMenuKeyboard(
  open: boolean,
  triggerRef: RefObject<HTMLElement | null>,
  menuRef: RefObject<HTMLElement | null>,
  view?: unknown,
): (event: KeyboardEvent) => void {
  const wasOpen = useRef(false);
  useLayoutEffect(() => {
    let frame = 0;
    if (open) {
      const first = menuItems(menuRef.current)[0];
      first?.focus();
      // A portalled menu stays visibility: hidden until AnchoredPortal has measured it, and a hidden
      // element does not take focus; by the next frame it is shown.
      if (first && document.activeElement !== first) frame = requestAnimationFrame(() => first.focus());
    } else if (wasOpen.current) {
      // The menu is gone, so focus that was in it is now on the body.
      const active = document.activeElement;
      if (!active || active === document.body) triggerRef.current?.focus();
    }
    wasOpen.current = open;
    return () => { if (frame) cancelAnimationFrame(frame); };
  }, [open, view, menuRef, triggerRef]);

  return (event: KeyboardEvent) => {
    const items = menuItems(menuRef.current);
    if (items.length === 0) return;
    const at = items.indexOf(document.activeElement as HTMLElement);
    let next: number;
    switch (event.key) {
      case "ArrowDown": next = (at + 1) % items.length; break;
      case "ArrowUp": next = at <= 0 ? items.length - 1 : at - 1; break;
      case "Home": next = 0; break;
      case "End": next = items.length - 1; break;
      default: return;
    }
    event.preventDefault();
    event.stopPropagation();
    items[next].focus();
  };
}
