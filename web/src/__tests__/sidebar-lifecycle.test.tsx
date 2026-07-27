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
  it("the icon-only new-chat button carries an accessible name", () => {
    render(<Sidebar {...baseProps} />);
    // t() echoes keys in tests; icon-only buttons must not be blank to a reader.
    expect(screen.getByLabelText("sidebar.new_chat")).toBeTruthy();
  });
});

describe("Sidebar ACTIVE SPAWNS lifecycle", () => {
  it("lists only spawns with an active chat", () => {
    render(<Sidebar {...baseProps} />);
    expect(screen.getByText("小美")).toBeDefined();
    expect(screen.queryByText("Mermer")).toBeNull();  // no active chat → hidden
  });
});

describe("Sidebar window chrome strip", () => {
  // v0.1.3: the decorative fake traffic-light buttons are gone — the packaged
  // shell overlays the REAL macOS controls in this corner (titleBarStyle
  // Overlay). The strip must contain no clickable decoys, only the build tag.
  it("has no fake traffic-light buttons, only the build tag", () => {
    render(<Sidebar {...baseProps} />);
    const strip = screen.getByTestId("window-chrome-strip");
    expect(strip.querySelectorAll("div").length).toBe(0);
    expect(strip.querySelectorAll("[class*='rounded-full']").length).toBe(0);
    expect(strip.textContent).toContain("sidebar.node_version");
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
