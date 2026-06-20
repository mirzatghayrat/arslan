/**
 * staged.test.tsx — TDD for Task 8 (staged orchestration frontend)
 * Tests: proposal confirm button + deliverable verdict bar in OrchestratorChat.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import OrchestratorChat from "../components/OrchestratorChat";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

// jsdom does not implement scrollIntoView — suppress the error
window.HTMLElement.prototype.scrollIntoView = vi.fn();

const baseProps = {
  setChatHistory: () => {},
  spawns: [],
  currentStyle: "linear" as const,
  setCurrentStyle: () => {},
  activeThread: { memberSpawnIds: [] },
};

describe("staged orchestration UI", () => {
  it("renders a confirm button on a proposal message and fires onConfirmDirection", async () => {
    const onConfirm = vi.fn();
    render(
      <OrchestratorChat
        {...baseProps}
        chatHistory={[
          {
            id: "p1",
            sender: "spawn",
            senderName: "领英智囊",
            senderAvatar: "sparkles",
            text: "proposed direction…",
            timestamp: "",
            isProposal: true,
            spawnId: "4",
          } as any,
        ]}
        onConfirmDirection={onConfirm}
      />,
    );

    // The button label is the i18n key (mock returns the key)
    const btn = screen.getByRole("button", { name: /orchestrator\.confirm_direction/i });
    await userEvent.click(btn);
    // spawnId is "4" (string) — should be converted to number 4
    expect(onConfirm).toHaveBeenCalledWith(4);
  });

  it("renders a verdict bar on a normal spawn deliverable and fires onDeliverableVerdict on accept", async () => {
    const onVerdict = vi.fn();
    render(
      <OrchestratorChat
        {...baseProps}
        chatHistory={[
          {
            id: "d1",
            sender: "spawn",
            senderName: "领英智囊",
            senderAvatar: "sparkles",
            text: "here is my deliverable",
            timestamp: "",
            spawnId: "7",
          } as any,
        ]}
        onDeliverableVerdict={onVerdict}
      />,
    );

    const acceptBtn = screen.getByRole("button", { name: /orchestrator\.verdict_accept/i });
    await userEvent.click(acceptBtn);
    expect(onVerdict).toHaveBeenCalledWith("accept", 7, undefined);
  });

  it("fires onDeliverableVerdict with 'discard' when discard is clicked", async () => {
    const onVerdict = vi.fn();
    render(
      <OrchestratorChat
        {...baseProps}
        chatHistory={[
          {
            id: "d2",
            sender: "spawn",
            senderName: "测试",
            senderAvatar: "cpu",
            text: "deliverable text",
            timestamp: "",
            spawnId: "3",
          } as any,
        ]}
        onDeliverableVerdict={onVerdict}
      />,
    );

    const discardBtn = screen.getByRole("button", { name: /orchestrator\.verdict_discard/i });
    await userEvent.click(discardBtn);
    expect(onVerdict).toHaveBeenCalledWith("discard", 3, undefined);
  });
});

describe("arslanStore — pendingProposalSpawnId flag", () => {
  beforeEach(() => {
    useArslanStore.setState(initialArslanState(), true);
  });

  it("clears pendingProposalSpawnId on an aborted stream_end, so the next real deliverable is NOT flagged isProposal", () => {
    const { handleFrame } = useArslanStore.getState();

    // 1. Proposal frame arrives for spawn 9 — sets pendingProposalSpawnId = 9
    handleFrame({ type: "proposal", spawn_id: 9 } as any);
    expect(useArslanStore.getState().pendingProposalSpawnId).toBe(9);

    // 2. Stream starts for spawn 9
    handleFrame({ type: "stream_start", source: "spawn", spawn_id: 9, spawn_name: "TestSpawn" } as any);

    // 3. Aborted stream_end (message_id null, no content, no steps)
    handleFrame({ type: "stream_end", message_id: null } as any);
    expect(useArslanStore.getState().pendingProposalSpawnId).toBeNull();

    // 4. A fresh normal deliverable from the SAME spawn must NOT be flagged isProposal
    handleFrame({ type: "stream_start", source: "spawn", spawn_id: 9, spawn_name: "TestSpawn" } as any);
    handleFrame({ type: "stream_chunk", content: "real output" } as any);
    handleFrame({ type: "stream_end", message_id: 42 } as any);

    const items = useArslanStore.getState().items;
    const deliverable = items.find((it) => it.id === 42);
    expect(deliverable).toBeDefined();
    expect((deliverable as any).isProposal).toBeUndefined();
  });
});
