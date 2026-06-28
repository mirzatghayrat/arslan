/**
 * feedback-refine.test.tsx — TDD for the light feedback UI (Task 2).
 *
 * Renders OrchestratorChat with one spawn deliverable (no verdict) and asserts:
 *  - 👍 / 👎 / 精修 controls render; NO redo button.
 *  - 👍 → onDeliverableVerdict('accept', 3, 42)
 *  - 👎 → onDeliverableVerdict('discard', 3, 42)
 *  - 精修 → onRefine(3, 42, 'OUT', '小美')
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll } from "vitest";
import OrchestratorChat from "../components/OrchestratorChat";
import SpawnDirectChat from "../components/SpawnDirectChat";

// Deterministic i18n — t returns the key.
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

// WS mock for SpawnDirectChat (mirror spawn-direct-chat-tools.test.tsx).
vi.mock("../hooks/useWebSocket", () => ({
  useWebSocket: () => ({ send: vi.fn(), reconnecting: false, setLastMessageId: vi.fn() }),
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
  it("renders the 正在精修 banner with the spawn name when refineDeliverable is set", () => {
    render(
      <SpawnDirectChat
        spawn={refineSpawn}
        currentStyle="quartz"
        refineDeliverable={"DELIVERABLE TEXT"}
        onFinalize={vi.fn()}
      />,
    );

    // Banner names the spawn + carries the 正在精修 marker (this also proves the
    // refineDeliverable seed path ran — same flag drives both).
    const banner = screen.getByText(/正在精修：小美/);
    expect(banner).toBeDefined();
    expect(banner.textContent).toContain("正在精修");
  });

  it("does NOT render the banner without refineDeliverable", () => {
    render(<SpawnDirectChat spawn={refineSpawn} currentStyle="quartz" />);
    expect(screen.queryByText(/正在精修：/)).toBeNull();
  });
});
