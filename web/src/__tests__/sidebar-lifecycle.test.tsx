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
});
