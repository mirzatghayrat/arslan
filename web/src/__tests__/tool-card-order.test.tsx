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
