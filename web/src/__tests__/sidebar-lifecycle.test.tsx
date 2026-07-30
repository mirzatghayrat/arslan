import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll } from "vitest";
import Sidebar from "../components/Sidebar";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const spawns = [
  { id: "1", name: "小美", domain: "content", totalTasks: 0, hasActiveChat: true } as any,
  { id: "2", name: "Mermer", domain: "pa", totalTasks: 0, hasActiveChat: false } as any,
];
const baseProps = {
  threads: [], activeThreadId: "", onSelectThread: () => {}, onAddThread: () => {},
  spawns, activeSpawnChatId: "", onSelectSpawnChat: () => {}, activeSection: "arslan" as const,
  onChangeSection: () => {}, onCompleteChat: vi.fn(),
  onDistillThread: vi.fn(), onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(),
  backendStatus: "online" as const,
  // decision (a): the list is scoped by dispatch; tests supply the set
  dispatchedSpawnIds: new Set<number>([1, 2]),
} as any;

describe("Sidebar a11y (M7-#5)", () => {
  it("the icon-only new-chat button carries an accessible name", () => {
    render(<Sidebar {...baseProps} />);
    // t() echoes keys in tests; icon-only buttons must not be blank to a reader.
    expect(screen.getByLabelText("sidebar.new_chat")).toBeTruthy();
  });
});

describe("Sidebar ACTIVE SPAWNS lifecycle", () => {
  // The rule CHANGED (decision (a)): the list is scoped to the spawns THIS
  // conversation dispatched to, not to the ones with a direct chat open. The
  // old assertion pinned the old rule and is replaced rather than relaxed —
  // both halves below, because either alone is satisfied by a list that shows
  // everything or nothing.
  it("lists a spawn this session dispatched to, even with no direct chat", () => {
    render(<Sidebar {...baseProps} dispatchedSpawnIds={new Set([2])} />);
    // Mermer has hasActiveChat: false, and is still listed — it is part of THIS
    // session's work, which is the question the list now answers.
    expect(screen.getByText("Mermer")).toBeDefined();
  });

  it("leaves out a spawn this session never dispatched to", () => {
    render(<Sidebar {...baseProps} dispatchedSpawnIds={new Set([2])} />);
    expect(screen.queryByText("小美")).toBeNull();
  });

  it("shows nothing when the session has dispatched to nobody", () => {
    // Not an error state: a fresh conversation has no spawns of its own yet,
    // and an empty list is the truthful answer.
    render(<Sidebar {...baseProps} dispatchedSpawnIds={new Set<number>()} />);
    expect(screen.queryByText("小美")).toBeNull();
    expect(screen.queryByText("Mermer")).toBeNull();
  });
});

describe("Sidebar window chrome strip", () => {
  // v0.1.3: the decorative fake traffic-light buttons are gone — the packaged
  // shell overlays the REAL macOS controls in this corner (titleBarStyle
  // Overlay). The strip must contain no clickable decoys, only the build tag.
  it("has no fake traffic-light buttons and no build tag", () => {
    render(<Sidebar {...baseProps} />);
    const strip = screen.getByTestId("window-chrome-strip");
    expect(strip.querySelectorAll("div").length).toBe(0);
    expect(strip.querySelectorAll("[class*='rounded-full']").length).toBe(0);
    // The build tag is gone (batch two). Asserting emptiness rather than the
    // absence of one string: any text here would sit under the real traffic
    // lights, which is why the strip carries none.
    expect(strip.textContent?.trim()).toBe("");
  });

  // The strip's HEIGHT is geometry, not decoration: the traffic lights are
  // placed at logical (13, 16), so a strip that collapsed to its padding would
  // put them on top of the brand header and shrink the drag region. Removing
  // the text must not be allowed to do that silently.
  it("keeps enough height for the real traffic lights", () => {
    render(<Sidebar {...baseProps} />);
    expect(
      screen.getByTestId("window-chrome-strip").className,
    ).toMatch(/h-\[41px\]/);
  });

  // The overlay title bar has no native strip to grab, so the strip must be
  // a subtree ("deep") drag region — bare/true would only drag on direct
  // container clicks, and a missing attribute makes the window unmovable.
  it("is a deep tauri drag region", () => {
    render(<Sidebar {...baseProps} />);
    expect(
      screen.getByTestId("window-chrome-strip").getAttribute("data-tauri-drag-region"),
    ).toBe("deep");
  });
});

describe("Sidebar selected-row marker", () => {
  // Batch two: the selected row used `border-l-2 border-primary` on a
  // `rounded-lg` element. A border follows the corner radius, so the indicator
  // rendered as a crescent rather than a line. The replacement is a straight
  // bar drawn over the row; these assertions pin BOTH halves, because either
  // one alone is satisfied by the old markup.
  it("marks the active row with a straight bar, not a rounded border", () => {
    render(<Sidebar {...baseProps} threads={[{ id: "t1", title: "one" }]}
                   activeSection="arslan" activeThreadId="t1" />);
    const row = document.getElementById("active-thread-btn-t1")!;
    expect(row).toBeTruthy();
    // (a) the bar exists and has no corner radius of its own
    const bar = row.querySelector("span[aria-hidden]");
    expect(bar).toBeTruthy();
    expect(bar!.className).not.toMatch(/rounded/);
    // (b) the coloured left border is gone — this is the half that regresses
    // if someone "simplifies" the marker back into a border
    expect(row.className).not.toMatch(/border-primary/);
  });

  it("keeps the row's left inset identical when unselected", () => {
    // Otherwise selecting a row shifts its text by 2px, which reads as a jump.
    render(<Sidebar {...baseProps} threads={[{ id: "t1", title: "one" }]}
                   activeSection="ledger" activeThreadId="t1" />);
    const row = document.getElementById("active-thread-btn-t1")!;
    expect(row.className).toMatch(/border-l-2/);
    expect(row.querySelector("span[aria-hidden]")).toBeNull();
  });
});
