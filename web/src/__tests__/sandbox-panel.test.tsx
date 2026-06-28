import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import SandboxPanel from "../components/SandboxPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: { name?: string }) => (o?.name ? `${k} ${o.name}` : k) }),
}));
// Capture outgoing frames + the inbound frame callback from the sandbox socket.
let sandboxFrameCb: (m: any) => void = () => {};
const sandboxSend = vi.fn();
vi.mock("../hooks/useWebSocket", () => ({
  useWebSocket: (_path: string, onMsg?: (m: any) => void) => {
    if (onMsg) sandboxFrameCb = onMsg;
    return { send: sandboxSend, reconnecting: false, setLastMessageId: vi.fn() };
  },
}));

beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });
beforeEach(() => { sandboxSend.mockClear(); });

const spawn = { id: "3", name: "小美", avatarEmoji: "🌸", domain: "content", status: "idle",
  tools: [], skills: [], totalTasks: 0 } as any;

describe("SandboxPanel", () => {
  it("renders header, seed label, and Confirm & Merge / Discard bar", () => {
    render(
      <SandboxPanel spawn={spawn} sessionId="sbx-1" seed="DELIVERABLE" conversationId="main"
        onClose={() => {}} onMerged={() => {}} />,
    );
    expect(screen.getByText(/小美/)).toBeDefined();
    expect(screen.getByText("orchestrator.sandbox_seed_label")).toBeDefined();
    expect(screen.getByText("orchestrator.sandbox_confirm_merge")).toBeDefined();
    expect(screen.getByText("orchestrator.sandbox_discard")).toBeDefined();
  });

  it("Confirm & Merge sends confirm_merge with the conversation id", () => {
    render(
      <SandboxPanel spawn={spawn} sessionId="s" seed={null} conversationId="main"
        onClose={() => {}} onMerged={() => {}} />,
    );
    // Drive one assistant reply so Confirm is enabled (hasContent gate).
    act(() => { sandboxFrameCb({ type: "stream_start" }); });
    act(() => { sandboxFrameCb({ type: "stream_chunk", content: "DRAFT" }); });
    act(() => { sandboxFrameCb({ type: "stream_end" }); });
    fireEvent.click(screen.getByText("orchestrator.sandbox_confirm_merge"));
    expect(sandboxSend).toHaveBeenCalledWith(
      expect.objectContaining({ type: "confirm_merge", conversation_id: "main" }),
    );
  });
});
