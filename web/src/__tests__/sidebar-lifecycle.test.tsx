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
} as any;

describe("Sidebar a11y (M7-#5)", () => {
  it("has exactly one way to start a conversation, and it says so in words", () => {
    // 0.1.47: the list header's icon-only "+" duplicated the labelled button at the top.
    render(<Sidebar {...baseProps} />);
    expect(screen.getAllByRole("button", { name: "workspace.newConversation" })).toHaveLength(1);
    expect(screen.queryByLabelText("sidebar.new_chat")).toBeNull();
  });

  it("has no Conversations entry: the conversation rows are the way back", () => {
    // It only switched to the last open conversation, which the highlighted row already does.
    render(<Sidebar {...baseProps} />);
    expect(document.getElementById("nav-btn-conversations-deck")).toBeNull();
    expect(screen.queryByText("workspace.conversations")).toBeNull();
  });
});

describe("Sidebar experts (0.1.42: experts live in the capability library)", () => {
  // The rule CHANGED again: the sidebar no longer carries "other expert work".
  // Only a chat the user opened with an expert is a conversation row; an expert
  // that is merely working or was dispatched is not listed here at all.
  it("lists conversations only — even a user-opened expert chat is not a row (0.1.44)", () => {
    render(<Sidebar {...baseProps} />);
    expect(screen.getByRole("region", { name: "workspace.recentConversations" })).not.toHaveTextContent("小美");
  });

  it("New conversation starts a conversation instead of opening an expert picker", () => {
    const onAddThread = vi.fn();
    render(<Sidebar {...baseProps} onAddThread={onAddThread} />);
    fireEvent.click(screen.getByRole("button", { name: "workspace.newConversation" }));
    expect(onAddThread).toHaveBeenCalledOnce();
    expect(screen.queryByText("Mermer")).toBeNull();
  });

  it("does not list a working expert the user never opened", () => {
    render(<Sidebar {...baseProps} spawns={[{ ...spawns[1], status: "working" }]} />);
    expect(screen.queryByText("Mermer")).toBeNull();
    expect(screen.queryByText(/workspace\.legacyWork/)).toBeNull();
  });

  it("does not infer user-opened chats from legacy task transcript existence", () => {
    render(<Sidebar {...baseProps} expertChatIds={[]} />);
    expect(screen.queryByText("小美")).toBeNull();
  });

  it("has no brand subtitle under the name", () => {
    render(<Sidebar {...baseProps} />);
    expect(screen.queryByText("sidebar.brand_subtitle")).toBeNull();
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
