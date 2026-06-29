/**
 * verdict-feedback.test.tsx — TDD for verdict_recorded visible feedback
 *
 * (a) store test: dispatch a spawn deliverable, then a verdict_recorded frame,
 *     assert the deliverable message is marked with verdict:'accept'.
 * (b) component test: render OrchestratorChat with a deliverable that has
 *     verdict:'accept', assert confirmed state is shown and accept button is absent.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import OrchestratorChat from "../components/OrchestratorChat";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

window.HTMLElement.prototype.scrollIntoView = vi.fn();

const baseProps = {
  setChatHistory: () => {},
  spawns: [],
  currentStyle: "linear" as const,
  setCurrentStyle: () => {},
  activeThread: { memberSpawnIds: [] },
};

// ---------------------------------------------------------------------------
// Store tests
// ---------------------------------------------------------------------------
describe("arslanStore — verdict_recorded marks the deliverable", () => {
  beforeEach(() => {
    useArslanStore.setState(initialArslanState(), true);
  });

  it("marks the most recent spawn deliverable for that spawn_id with verdict:'accept'", () => {
    const { handleFrame } = useArslanStore.getState();

    // Produce a spawn deliverable via streaming (spawn_id=7)
    handleFrame({ type: "routing", spawn_id: 7, spawn_name: "Nexus" } as any);
    handleFrame({ type: "stream_start", source: "spawn", spawn_id: 7 } as any);
    handleFrame({ type: "stream_chunk", content: "Here is my deliverable" } as any);
    handleFrame({ type: "stream_end", message_id: 42 } as any);

    // Verify the item was created with no verdict yet
    const itemsBefore = useArslanStore.getState().items;
    const deliverable = itemsBefore.find((it) => it.id === 42);
    expect(deliverable).toBeDefined();
    expect((deliverable as any).verdict).toBeUndefined();

    // Now dispatch the verdict_recorded ack
    handleFrame({ type: "verdict_recorded", spawn_id: 7, action: "accept" } as any);

    const itemsAfter = useArslanStore.getState().items;
    const markedItem = itemsAfter.find((it) => it.id === 42);
    expect(markedItem).toBeDefined();
    expect((markedItem as any).verdict).toBe("accept");
  });

  it("marks with verdict:'discard' for a discard action", () => {
    const { handleFrame } = useArslanStore.getState();

    handleFrame({ type: "routing", spawn_id: 3, spawn_name: "Alpha" } as any);
    handleFrame({ type: "stream_start", source: "spawn", spawn_id: 3 } as any);
    handleFrame({ type: "stream_chunk", content: "Another deliverable" } as any);
    handleFrame({ type: "stream_end", message_id: 99 } as any);

    handleFrame({ type: "verdict_recorded", spawn_id: 3, action: "discard" } as any);

    const item = useArslanStore.getState().items.find((it) => it.id === 99);
    expect((item as any).verdict).toBe("discard");
  });

  it("does not mark a proposal (isProposal=true) item with verdict", () => {
    const { handleFrame } = useArslanStore.getState();

    // A proposal then a deliverable for spawn 5
    handleFrame({ type: "proposal", spawn_id: 5 } as any);
    handleFrame({ type: "routing", spawn_id: 5, spawn_name: "Beta" } as any);
    handleFrame({ type: "stream_start", source: "spawn", spawn_id: 5 } as any);
    handleFrame({ type: "stream_chunk", content: "Proposed plan…" } as any);
    handleFrame({ type: "stream_end", message_id: 55 } as any);

    // Proposal should have isProposal = true
    const proposal = useArslanStore.getState().items.find((it) => it.id === 55);
    expect((proposal as any).isProposal).toBe(true);

    // verdict_recorded should NOT mark this isProposal item
    handleFrame({ type: "verdict_recorded", spawn_id: 5, action: "accept" } as any);

    const proposalAfter = useArslanStore.getState().items.find((it) => it.id === 55);
    expect((proposalAfter as any).verdict).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Component tests
// ---------------------------------------------------------------------------
describe("OrchestratorChat — verdict confirmed state", () => {
  it("shows voted state (filled thumbs) and hides buttons when msg.verdict is 'accept'", () => {
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
            verdict: "accept",
          } as any,
        ]}
        onDeliverableVerdict={vi.fn()}
      />,
    );

    // The voted marker is shown with the correct verdict
    const voted = screen.getByTestId("verdict-voted");
    expect(voted.getAttribute("data-verdict")).toBe("accept");

    // The vote buttons are NOT present
    expect(screen.queryByTitle("orchestrator.verdict_like")).toBeNull();
    expect(screen.queryByTitle("orchestrator.verdict_dislike")).toBeNull();
  });

  it("shows voted state with discard and hides buttons when msg.verdict is 'discard'", () => {
    render(
      <OrchestratorChat
        {...baseProps}
        chatHistory={[
          {
            id: "d2",
            sender: "spawn",
            senderName: "Alpha",
            senderAvatar: "cpu",
            text: "deliverable text",
            timestamp: "",
            spawnId: "3",
            verdict: "discard",
          } as any,
        ]}
        onDeliverableVerdict={vi.fn()}
      />,
    );

    const voted = screen.getByTestId("verdict-voted");
    expect(voted.getAttribute("data-verdict")).toBe("discard");
    expect(screen.queryByTitle("orchestrator.verdict_like")).toBeNull();
    expect(screen.queryByTitle("orchestrator.verdict_dislike")).toBeNull();
  });
});
