/** D3 (0.1.55): the tool steps ran before the answer, so their card sits ABOVE the
 *  answer text — in all three chat styles. It used to come after the text. */
import { describe, it, expect, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import React from "react";
import OrchestratorChat from "../components/OrchestratorChat";
import type { Message } from "../types";

window.HTMLElement.prototype.scrollIntoView = vi.fn();
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { resolvedLanguage: "en", language: "en" } }),
  Trans: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const answer: Message = {
  id: "m1", sender: "arslan", senderName: "Arslan", senderAvatar: "🦁", timestamp: "",
  text: "THE-ANSWER-TEXT",
  toolActivity: { id: "t1", toolName: "run_command", emoji: "", status: "completed", stepStatus: "ok",
    action: "ran a command", outputSummary: "ok", collapsed: true },
} as Message;

describe.each(["quartz", "brutalist", "linear"] as const)("chat style %s", (style) => {
  it("puts the tool card before the answer", () => {
    render(<OrchestratorChat chatHistory={[answer]} setChatHistory={() => {}} spawns={[]}
      currentStyle={style} setCurrentStyle={() => {}} activeThread={null} />);
    const card = screen.getByTestId("tool-activity-card");
    const text = screen.getByText("THE-ANSWER-TEXT");
    expect(card.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    cleanup();
  });
});

/** 0.1.55 S5: a legacy expert's escalation is one kit Notice in every style (was three banners). */
describe.each(["quartz", "brutalist", "linear"] as const)("escalation in style %s", (style) => {
  it.each([["need_raised", "warn"], ["arslan_resolving", "info"], ["resolved", "info"], ["refused", "error"]] as const)(
    "%s reads as a %s notice with the issue and the resolution", (status, tone) => {
      const msg = { id: "e1", sender: "spawn", senderName: "Writer", senderAvatar: "", timestamp: "", text: "",
        escalation: { status, spawnName: "Writer", issue: "needs a login", resolutionMessage: status === "refused" ? "not allowed" : undefined },
      } as unknown as Message;
      render(<OrchestratorChat chatHistory={[msg]} setChatHistory={() => {}} spawns={[]}
        currentStyle={style} setCurrentStyle={() => {}} activeThread={null} />);
      const notices = screen.getAllByTestId("escalation-notice");
      expect(notices).toHaveLength(1);
      expect(notices[0]).toHaveAttribute("data-tone", tone);
      expect(notices[0]).toHaveTextContent("needs a login");
      expect(notices[0]).toHaveTextContent("Writer");
      if (status === "refused") expect(notices[0]).toHaveTextContent("not allowed");
      cleanup();
    });
});

/** 0.1.56 §7: Arslan's proposed plan change is a card in the conversation, in every style. */
describe.each(["quartz", "brutalist", "linear"] as const)("plan proposal in style %s", (style) => {
  it("renders the card, not a bubble", () => {
    const msg = { id: "pp", sender: "arslan", senderName: "Arslan", senderAvatar: "", timestamp: "", text: "no online mode",
      planProposal: { projectId: "p1", id: "pp1", reason: "no online mode", cleared: 1, diff: [{ op: "remove", level: "Stress test" }] },
    } as unknown as Message;
    render(<OrchestratorChat chatHistory={[msg]} setChatHistory={() => {}} spawns={[]}
      currentStyle={style} setCurrentStyle={() => {}} activeThread={null} />);
    expect(screen.getByTestId("plan-proposal")).toBeInTheDocument();
    expect(screen.getByTestId("plan-diff")).toHaveTextContent("projectsUI.diffRemove");
    cleanup();
  });
});
