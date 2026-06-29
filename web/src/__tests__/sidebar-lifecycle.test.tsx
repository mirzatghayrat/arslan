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
  backendStatus: "online" as const,
} as any;

describe("Sidebar ACTIVE SPAWNS lifecycle", () => {
  it("lists only spawns with an active chat", () => {
    render(<Sidebar {...baseProps} />);
    expect(screen.getByText("小美")).toBeDefined();
    expect(screen.queryByText("Mermer")).toBeNull();  // no active chat → hidden
  });
});
