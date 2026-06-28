/**
 * feedback-refine.test.tsx — TDD for the light feedback UI (Task 2).
 *
 * Renders OrchestratorChat with one spawn deliverable (no verdict) and asserts:
 *  - 👍 / 👎 / 精修 controls render; NO redo button.
 *  - 👍 → onDeliverableVerdict('accept', 3, 42)
 *  - 👎 → onDeliverableVerdict('discard', 3, 42)
 *  - 精修 → onRefine(3, 42, 'OUT', '小美')
 */

import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import OrchestratorChat from "../components/OrchestratorChat";
import SpawnDirectChat from "../components/SpawnDirectChat";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

// Deterministic i18n — t returns the key, appending the interpolated name when present so
// name-carrying strings (e.g. the refine banner) stay assertable.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: { name?: string }) => (opts?.name ? `${k} ${opts.name}` : k),
  }),
}));

// WS mock for SpawnDirectChat — capture the frame callback + the send spy so tests
// can drive incoming frames and inspect outgoing frames (mirror spawn-direct-chat-tools).
let frameCb: (m: any) => void = () => {};
const sendSpy = vi.fn();
vi.mock("../hooks/useWebSocket", () => ({
  useWebSocket: (_path: string, onMessage?: (m: any) => void) => {
    if (onMessage) frameCb = onMessage;
    return { send: sendSpy, reconnecting: false, setLastMessageId: vi.fn() };
  },
}));

vi.mock("../api/client", () => ({
  api: {
    extractAttachmentUrl: vi.fn(),
    extractAttachmentFile: vi.fn(),
  },
}));

beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  sendSpy.mockClear();
});

const baseProps = {
  setChatHistory: () => {},
  spawns: [],
  currentStyle: "quartz" as const,
  setCurrentStyle: () => {},
  activeThread: { memberSpawnIds: [] },
};

const deliverable = {
  id: "d1",
  sender: "spawn",
  senderName: "小美",
  senderAvatar: "sparkles",
  text: "OUT",
  timestamp: "",
  spawnId: "3",
  messageId: 42,
  spawnName: "小美",
} as any;

describe("OrchestratorChat — light feedback UI (👍/👎/精修)", () => {
  it("renders 👍 / 👎 / 精修 and NO redo button; wires the handlers", () => {
    const onDeliverableVerdict = vi.fn();
    const onRefine = vi.fn();
    render(
      <OrchestratorChat
        {...baseProps}
        chatHistory={[deliverable]}
        onDeliverableVerdict={onDeliverableVerdict}
        onRefine={onRefine}
      />,
    );

    // The 精修 label renders (from t('orchestrator.refine')).
    expect(screen.getByText("orchestrator.refine")).toBeDefined();

    // No redo button.
    expect(screen.queryByText("orchestrator.verdict_redo")).toBeNull();

    // 👍 — button with the like title.
    const like = screen.getByTitle("orchestrator.verdict_like");
    fireEvent.click(like);
    expect(onDeliverableVerdict).toHaveBeenCalledWith("accept", 3, 42);

    // 👎 — button with the dislike title.
    const dislike = screen.getByTitle("orchestrator.verdict_dislike");
    fireEvent.click(dislike);
    expect(onDeliverableVerdict).toHaveBeenCalledWith("discard", 3, 42);

    // 精修 — refine button.
    fireEvent.click(screen.getByText("orchestrator.refine"));
    expect(onRefine).toHaveBeenCalledWith(3, 42, "OUT", "小美");
  });
});

const refineSpawn = {
  id: "3",
  name: "小美",
  avatarEmoji: "🌸",
  domain: "Test",
  description: "Test spawn",
  status: "idle" as const,
  tools: [],
  skills: [],
  totalTasks: 0,
} as any;

describe("SpawnDirectChat — refine handoff (banner + seed)", () => {
  it("renders the refine banner with the spawn name when refineDeliverable is set", () => {
    render(
      <SpawnDirectChat
        spawn={refineSpawn}
        currentStyle="quartz"
        refineDeliverable={"DELIVERABLE TEXT"}
        onFinalize={vi.fn()}
      />,
    );

    // Banner is i18n-driven (spawn_chat.refine_banner) and names the spawn — this also
    // proves the refineDeliverable seed path ran (same flag drives both).
    const banner = screen.getByText(/spawn_chat\.refine_banner 小美/);
    expect(banner).toBeDefined();
    expect(banner.textContent).toContain("小美");
  });

  it("does NOT render the banner without refineDeliverable", () => {
    render(<SpawnDirectChat spawn={refineSpawn} currentStyle="quartz" />);
    expect(screen.queryByText(/spawn_chat\.refine_banner/)).toBeNull();
  });
});

describe("SpawnDirectChat — refine send + 定稿 (Part A + Task 4)", () => {
  it("includes the deliverable in attached_context on send during refine mode", () => {
    render(
      <SpawnDirectChat
        spawn={refineSpawn}
        currentStyle="quartz"
        refineDeliverable={"DELIVERABLE TEXT"}
        onFinalize={vi.fn()}
      />,
    );

    const input = screen.getByPlaceholderText("spawn_chat.placeholder_input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "tighten the intro" } });
    fireEvent.submit(input.closest("form")!);

    const userFrame = sendSpy.mock.calls
      .map((c) => c[0])
      .find((f: any) => f?.type === "user_message");
    expect(userFrame).toBeDefined();
    expect(userFrame.attached_context).toContain("DELIVERABLE TEXT");
    expect(userFrame.attached_names).toContain("spawn_chat.refine_attach_name");
  });

  it("renders 定稿 and calls onFinalize with the latest assistant reply", () => {
    const onFinalize = vi.fn();
    render(
      <SpawnDirectChat
        spawn={refineSpawn}
        currentStyle="quartz"
        refineDeliverable={"DELIVERABLE TEXT"}
        onFinalize={onFinalize}
      />,
    );

    // Drive the WS mock to deliver an assistant reply "REFINED".
    act(() => { frameCb({ type: "stream_start", message_id: 0 }); });
    act(() => { frameCb({ type: "stream_chunk", content: "REFINED" }); });
    act(() => { frameCb({ type: "stream_end", message_id: 88 }); });

    const finalizeBtn = screen.getByText("spawn.finalize_to_main");
    fireEvent.click(finalizeBtn);
    expect(onFinalize).toHaveBeenCalledWith("REFINED");
  });

  it("does not finalize a partial reply mid-stream (定稿 disabled while streaming)", () => {
    const onFinalize = vi.fn();
    render(
      <SpawnDirectChat
        spawn={refineSpawn}
        currentStyle="quartz"
        refineDeliverable={"DELIVERABLE TEXT"}
        onFinalize={onFinalize}
      />,
    );
    // Stream is in flight (no stream_end) → reply is partial.
    act(() => { frameCb({ type: "stream_start", message_id: 0 }); });
    act(() => { frameCb({ type: "stream_chunk", content: "PARTIA" }); });

    const finalizeBtn = screen.getByText("spawn.finalize_to_main").closest("button")!;
    expect(finalizeBtn).toBeDisabled();
    fireEvent.click(finalizeBtn);
    expect(onFinalize).not.toHaveBeenCalled();
  });
});

describe("arslanStore — deliverable_finalized", () => {
  beforeEach(() => useArslanStore.setState(initialArslanState(), true));

  it("appends a spawn item carrying refinedFrom", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame({
      type: "deliverable_finalized",
      spawn_id: 3,
      message_id: 77,
      content: "REFINED",
      refined_from: 42,
      spawn_name: "小美",
    } as any);

    const items = store().items;
    const last = items[items.length - 1];
    expect(last.role).toBe("spawn");
    expect(last.spawnId).toBe(3);
    expect(last.content).toBe("REFINED");
    expect(last.refinedFrom).toBe(42);
    expect(last.spawnName).toBe("小美");
  });
});
