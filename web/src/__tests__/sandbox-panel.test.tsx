import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import SandboxPanel from "../components/SandboxPanel";
import OrchestratorChat from "../components/OrchestratorChat";
import { useArslanStore } from "../stores/arslanStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: { name?: string }) => (o?.name ? `${k} ${o.name}` : k) }),
}));

vi.mock("../api/client", () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
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

  it("renders an HTML deliverable as a preview card, not raw source (parity with main chat)", () => {
    render(
      <SandboxPanel spawn={spawn} sessionId="s" seed={null} conversationId="main"
        onClose={() => {}} onMerged={() => {}} />,
    );
    const html = "<!DOCTYPE html><html><head><title>t</title></head><body><h1>Hi</h1><p>report body</p></body></html>";
    act(() => { sandboxFrameCb({ type: "stream_start" }); });
    act(() => { sandboxFrameCb({ type: "stream_chunk", content: html }); });
    act(() => { sandboxFrameCb({ type: "stream_end" }); });
    // baked into the same sandboxed html-doc card as OrchestratorChat, not a raw <!DOCTYPE wall
    expect(screen.getByTestId("html-doc-card")).toBeDefined();
  });

  it("humanizes tool activity instead of showing a raw 🔧 web_search", () => {
    render(
      <SandboxPanel spawn={spawn} sessionId="s" seed={null} conversationId="main"
        onClose={() => {}} onMerged={() => {}} />,
    );
    act(() => { sandboxFrameCb({ type: "stream_start" }); });
    act(() => { sandboxFrameCb({ type: "tool_call", tool: "web_search", args_summary: '{"query":"OKX"}' }); });
    act(() => { sandboxFrameCb({ type: "tool_result", tool: "web_search", ok: true, summary: "5 results" }); });
    act(() => { sandboxFrameCb({ type: "stream_chunk", content: "done" }); });
    act(() => { sandboxFrameCb({ type: "stream_end" }); });
    expect(screen.queryByText(/🔧 web_search/)).toBeNull();     // no raw tool id
    expect(screen.getByText("activity.search_q")).toBeDefined();   // humanized (i18n key via the t-mock)
  });

  it("shows a live thinking indicator during the pre-first-token gap (parity with main chat)", () => {
    render(
      <SandboxPanel spawn={spawn} sessionId="s" seed={null} conversationId="main"
        onClose={() => {}} onMerged={() => {}} />,
    );
    act(() => { sandboxFrameCb({ type: "stream_start" }); });                    // stream open, no token yet
    expect(screen.getByTestId("live-activity")).toBeDefined();
    act(() => { sandboxFrameCb({ type: "stream_chunk", content: "DRAFT" }); });  // first token arrives
    expect(screen.queryByTestId("live-activity")).toBeNull();                    // indicator gone …
    expect(screen.getByText("DRAFT")).toBeDefined();                             // … content shows
  });
});

const deliverable = { id: "d1", sender: "spawn", senderName: "小美", senderAvatar: "x", text: "OUT",
  timestamp: "", spawnId: "3", messageId: 42, spawnName: "小美" } as any;
const ocBaseProps = { setChatHistory: () => {}, spawns: [spawn], currentStyle: "quartz" as const,
  setCurrentStyle: () => {}, activeThread: { memberSpawnIds: ["3"] }, conversationId: "main" } as any;

describe("OrchestratorChat — refine opens a sandbox (not full-nav)", () => {
  it("clicking 精修 opens the sandbox panel seeded with the deliverable", () => {
    useArslanStore.setState({ roster: [{ spawnId: 3, name: "小美", status: "idle" }] } as never);
    render(<OrchestratorChat {...ocBaseProps} chatHistory={[deliverable]} />);
    fireEvent.click(screen.getByText("orchestrator.refine"));
    expect(screen.getByText("orchestrator.sandbox_confirm_merge")).toBeDefined();
    expect(screen.getByText("orchestrator.sandbox_seed_label")).toBeDefined();
  });
});
