import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll } from "vitest";
import OrchestratorChat from "../components/OrchestratorChat";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../hooks/useWebSocket", () => ({
  useWebSocket: () => ({ send: vi.fn(), reconnecting: false, setLastMessageId: vi.fn() }),
}));
vi.mock("../api/client", () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const spawnObj = { id: "3", name: "小美", avatarEmoji: "🌸", domain: "content", status: "idle", tools: [], skills: [], totalTasks: 0 } as any;
const deliverable = { id: "d1", sender: "spawn", senderName: "小美", senderAvatar: "x", text: "OUT", timestamp: "", spawnId: "3", messageId: 42, spawnName: "小美" } as any;
const baseProps = { setChatHistory: () => {}, spawns: [spawnObj], currentStyle: "quartz" as const, setCurrentStyle: () => {}, activeThread: { memberSpawnIds: [] }, conversationId: "main" } as any;

describe("OrchestratorChat — optimistic 👍/👎", () => {
  it("clicking 👍 immediately shows the voted state without any WS frame", () => {
    const onDeliverableVerdict = vi.fn();
    render(<OrchestratorChat {...baseProps} chatHistory={[deliverable]} onDeliverableVerdict={onDeliverableVerdict} />);
    // Before: no voted marker.
    expect(screen.queryByTestId("verdict-voted")).toBeNull();
    fireEvent.click(screen.getByTitle("orchestrator.verdict_like"));
    // After click: the bar is in its voted state (filled), and the handler still fired.
    const voted = screen.getByTestId("verdict-voted");
    expect(voted.getAttribute("data-verdict")).toBe("accept");
    expect(onDeliverableVerdict).toHaveBeenCalledWith("accept", 3, 42);
  });
});
