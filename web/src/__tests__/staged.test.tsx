/**
 * staged.test.tsx — TDD for Task 8 (staged orchestration frontend)
 * The store still acknowledges the legacy verdict frames; the chat no longer offers the actions.
 */

import { render, screen } from "@testing-library/react";
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

describe("an old expert message (0.1.48: the expert actions are gone)", () => {
  it("keeps copy but offers no confirm-direction, verdict or refine button", () => {
    for (const isProposal of [true, false]) {
      const { unmount } = render(
        <OrchestratorChat
          {...baseProps}
          chatHistory={[{
            id: "p1", sender: "spawn", senderName: "Expert", senderAvatar: "sparkles",
            text: "an old deliverable", timestamp: "", isProposal, spawnId: "4",
          } as any]}
        />,
      );
      expect(screen.getByText("an old deliverable")).toBeInTheDocument();
      // Each of these sent a WS message the server no longer handles.
      expect(screen.queryByRole("button", { name: /orchestrator\.confirm_direction/ })).toBeNull();
      expect(screen.queryByTitle("orchestrator.verdict_like")).toBeNull();
      expect(screen.queryByTitle("orchestrator.verdict_dislike")).toBeNull();
      expect(screen.queryByTitle("orchestrator.refine")).toBeNull();
      unmount();
    }
  });
});

describe("arslanStore — verdict_recorded ack", () => {
  beforeEach(() => {
    useArslanStore.setState(initialArslanState(), true);
  });

  it("handles verdict_recorded frame without throwing or changing items", () => {
    const { handleFrame } = useArslanStore.getState();
    const itemsBefore = useArslanStore.getState().items;
    // Should not throw; the frame is silently acknowledged
    handleFrame({ type: "verdict_recorded", spawn_id: 5, action: "accept" } as any);
    expect(useArslanStore.getState().items).toEqual(itemsBefore);
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
