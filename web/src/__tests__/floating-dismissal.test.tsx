/**
 * The floating-element class: not clipped, and dismissable two ways.
 *
 * Reported on the sidebar's conversation "···" menu — the bottom row's menu was
 * cut off by the thread list's `overflow-y-auto`, and neither an outside click
 * nor Escape closed it. Measured before any fix, so the round started from
 * facts rather than the report:
 *
 *     opens ....................................... yes
 *     closes when the BACKDROP itself is clicked .. yes
 *     closes on a click anywhere else ............. NO
 *     closes on Escape ............................ NO
 *
 * So dismissal was not missing, it was implemented as LAYOUT: a `fixed inset-0`
 * backdrop only covers the viewport while no ancestor establishes a containing
 * block, and its z-index only orders it inside its own stacking context.
 * Six components hand-rolled that backdrop; three others listened for Escape;
 * the two sets barely overlapped, which is why this kept resurfacing in a
 * different corner. Hence shared primitives rather than a local patch.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import ThreadRowMenu from "../components/ThreadRowMenu";

const props = {
  threadId: "t1",
  onDistill: vi.fn(), onArchive: vi.fn(), onUnarchive: vi.fn(), onDelete: vi.fn(),
};

beforeEach(() => vi.clearAllMocks());

function openMenu() {
  const utils = render(
    // A scrolling ancestor, exactly like the sidebar's thread list. The whole
    // point of the portal is that this must NOT contain the menu.
    <div data-testid="scroller" className="overflow-y-auto max-h-40">
      <ThreadRowMenu {...props} />
    </div>,
  );
  fireEvent.click(screen.getByRole("button", { name: /sidebar.thread_menu/i }));
  return utils;
}

describe("floating menus are dismissable", () => {
  it("closes on a click anywhere outside", () => {
    openMenu();
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes on Escape", () => {
    openMenu();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("does NOT close on a click inside the menu", () => {
    // Discriminating: a listener that closed on every document mousedown would
    // satisfy both tests above and make the menu unusable — the first click on
    // an item would dismiss it before the item ran.
    openMenu();
    fireEvent.mouseDown(screen.getByRole("menu"));
    expect(screen.queryByRole("menu")).toBeTruthy();
  });

  it("does NOT close on a click on its own trigger", () => {
    // The trigger toggles. If the outside-click handler treated it as outside,
    // mousedown would close and the click would reopen — a menu that can never
    // be dismissed by the button that opened it.
    openMenu();
    const trigger = screen.getByRole("button", { name: /sidebar.thread_menu/i });
    fireEvent.mouseDown(trigger);
    expect(screen.queryByRole("menu")).toBeTruthy();
  });

  it("still runs the action it was opened for", () => {
    // Discriminating: dismissal that swallowed the click would look correct in
    // every test above while quietly disabling every menu item.
    openMenu();
    fireEvent.click(screen.getByText("sidebar.distill"));
    expect(props.onDistill).toHaveBeenCalledWith("t1");
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("floating menus escape their clipping ancestor", () => {
  it("renders outside the scrolling container, not inside it", () => {
    openMenu();
    const scroller = screen.getByTestId("scroller");
    const menu = screen.getByRole("menu");
    expect(scroller.contains(menu)).toBe(false);
    // …and specifically at the document root, where no ancestor can clip it.
    expect(document.body.contains(menu)).toBe(true);
  });

  it("is positioned as a viewport-fixed layer", () => {
    openMenu();
    const layer = screen.getByTestId("anchored-portal");
    expect(layer.style.position).toBe("fixed");
  });
});


describe("AnchoredPortal flips up near the bottom edge", () => {
  /** jsdom gives every element a 0x0 rect, so a flip test that does not feed
   *  real geometry measures nothing. These stub the anchor's rect and the
   *  floating element's size, which is the only way the branch is reachable. */
  function renderAt(anchorTop: number, menuHeight = 160) {
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
    Object.defineProperty(window, "innerWidth", { value: 1200, configurable: true });
    const rect = { top: anchorTop, bottom: anchorTop + 20, left: 100, right: 140,
                   width: 40, height: 20, x: 100, y: anchorTop, toJSON: () => ({}) };
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue(rect as DOMRect);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(menuHeight);
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(208);
    openMenu();
    return screen.getByTestId("anchored-portal");
  }

  it("opens BELOW when there is room", () => {
    const layer = renderAt(100);
    expect(parseFloat(layer.style.top)).toBeGreaterThan(100);
    vi.restoreAllMocks();
  });

  it("opens ABOVE when the anchor is near the bottom", () => {
    // The reported case: the LAST conversation row.
    const layer = renderAt(760);          // bottom = 780, only 20px below in an 800px window
    expect(parseFloat(layer.style.top)).toBeLessThan(760);
    vi.restoreAllMocks();
  });

  it("keeps a right-aligned menu on screen on a narrow window", () => {
    Object.defineProperty(window, "innerWidth", { value: 240, configurable: true });
    const layer = renderAt(100);
    expect(parseFloat(layer.style.left)).toBeGreaterThanOrEqual(8);
    vi.restoreAllMocks();
  });
});
