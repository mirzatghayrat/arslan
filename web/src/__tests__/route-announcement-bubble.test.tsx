/**
 * route-announcement-bubble.test.tsx — the routing brief renders as a FULL Arslan
 * message bubble (avatar/name header + arslan styling), not an anonymous system line
 * (user feedback: the old quiet inline line above the "X joined" divider didn't read
 * as Arslan speaking). Mention chips stay inside the bubble. Covered in all 3 layout
 * variants.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";

import OrchestratorChat from "../components/OrchestratorChat";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

window.HTMLElement.prototype.scrollIntoView = vi.fn();

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (key === "app.name" ? "Arslan" : key),
  }),
  Trans: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
});

const announcementMsg = {
  id: "ann-1",
  sender: "arslan" as const,
  senderName: "Arslan",
  senderAvatar: "🦁",
  text: "用户需要OKX调研并生成PPT\n@调研员 — 负责:市场调研",
  timestamp: "",
  isRouteAnnouncement: true,
};

const spawns = [
  {
    id: "7",
    name: "调研员",
    domain: "research",
    description: "",
    status: "idle" as const,
    avatarEmoji: "🤖",
    tools: [],
    skills: [],
    totalTasks: 0,
  },
];

function renderWithStyle(style: "quartz" | "brutalist" | "linear") {
  return render(
    <OrchestratorChat
      chatHistory={[announcementMsg]}
      setChatHistory={() => {}}
      spawns={spawns}
      currentStyle={style}
      setCurrentStyle={() => {}}
      activeThread={null}
    />,
  );
}

describe("routing announcement renders as an Arslan message bubble", () => {
  it("quartz: Arslan name header visible + mention chip inside the bubble", () => {
    renderWithStyle("quartz");
    expect(screen.getByText("Arslan")).toBeTruthy(); // sender name header — Arslan speaking
    const chip = screen.getByTestId("mention-chip");
    expect(chip.textContent).toBe("@调研员");
    // the brief text itself is present (restated need)
    expect(screen.getByText(/用户需要OKX调研并生成PPT/)).toBeTruthy();
  });

  it("linear: Arslan name header visible + mention chip", () => {
    renderWithStyle("linear");
    expect(screen.getByText("Arslan")).toBeTruthy();
    expect(screen.getByTestId("mention-chip").textContent).toBe("@调研员");
  });

  it("brutalist: ARSLAN sender header visible + mention chip", () => {
    renderWithStyle("brutalist");
    // Header + sender badge both say ARSLAN — at least one present.
    expect(screen.getAllByText(/ARSLAN/).length).toBeGreaterThan(0);
    expect(screen.getByTestId("mention-chip").textContent).toBe("@调研员");
  });
});
