/**
 * staged.test.tsx — TDD for Task 8 (staged orchestration frontend)
 * An old expert message still shows; the chat no longer offers the expert actions.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import OrchestratorChat from "../components/OrchestratorChat";

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
    render(
      <OrchestratorChat
        {...baseProps}
        chatHistory={[{
          id: "p1", sender: "spawn", senderName: "Expert", senderAvatar: "sparkles",
          text: "an old deliverable", timestamp: "", spawnId: "4",
        } as any]}
      />,
    );
    expect(screen.getByText("an old deliverable")).toBeInTheDocument();
    // Each of these sent a WS message the server no longer handles.
    expect(screen.queryByRole("button", { name: /orchestrator\.confirm_direction/ })).toBeNull();
    expect(screen.queryByTitle("orchestrator.verdict_like")).toBeNull();
    expect(screen.queryByTitle("orchestrator.verdict_dislike")).toBeNull();
    expect(screen.queryByTitle("orchestrator.refine")).toBeNull();
  });
});
