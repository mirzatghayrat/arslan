/**
 * Sidebar — Second Brain nav entry.
 *
 * Coverage:
 *  1. The "Second Brain" entry renders (by its stable id + i18n key).
 *  2. Clicking it calls onChangeSection('brain').
 *  3. When active, it gets the active-state treatment (border-primary).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";

import Sidebar from "../components/Sidebar";

// i18n → return the key verbatim so assertions are locale-independent.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.count !== "undefined" ? `${opts.count}` : key,
  }),
}));

// motion/react → passthrough (no animation in jsdom).
vi.mock("motion/react", () => ({
  motion: new Proxy({}, { get: () => (p: Record<string, unknown>) => <div {...p} /> }),
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

function baseProps(overrides: Partial<React.ComponentProps<typeof Sidebar>> = {}) {
  return {
    threads: [],
    activeThreadId: "",
    onSelectThread: vi.fn(),
    onAddThread: vi.fn(),
    spawns: [],
    activeSpawnChatId: "",
    onSelectSpawnChat: vi.fn(),
    activeSection: "arslan" as const,
    onChangeSection: vi.fn(),
    onCompleteChat: vi.fn(),
    backendStatus: "online" as const,
    ...overrides,
  };
}

describe("Sidebar · Second Brain", () => {
  it("renders the Second Brain nav entry", () => {
    const { container } = render(<Sidebar {...baseProps()} />);
    const btn = container.querySelector("#nav-btn-brain-deck");
    expect(btn).not.toBeNull();
    expect(screen.getByText("nav.secondBrain")).toBeTruthy();
  });

  it("calls onChangeSection('brain') when clicked", () => {
    const onChangeSection = vi.fn();
    const { container } = render(<Sidebar {...baseProps({ onChangeSection })} />);
    fireEvent.click(container.querySelector("#nav-btn-brain-deck")!);
    expect(onChangeSection).toHaveBeenCalledWith("brain");
  });

  it("shows active state when the brain section is active", () => {
    const { container } = render(<Sidebar {...baseProps({ activeSection: "brain" })} />);
    const btn = container.querySelector("#nav-btn-brain-deck")!;
    expect(btn.className).toContain("border-primary");
  });
});
