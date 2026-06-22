/**
 * Task UX5 — No-model hint in orchestrator chat.
 *
 * TDD: tests written first. They drive the NoModelHint component.
 *
 * Strategy: test the tiny presentational NoModelHint component in isolation
 * so we don't need to render the full App or OrchestratorChat with all
 * their mocks.
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import NoModelHint from "../components/NoModelHint";

describe("NoModelHint", () => {
  it("renders hint text and Open Settings button when hasModel is false", () => {
    render(<NoModelHint hasModel={false} onOpenSettings={vi.fn()} />);
    // The i18n key passthrough returns the key itself
    expect(screen.getByText("orchestrator.no_model_hint")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /orchestrator\.open_settings/i })).toBeInTheDocument();
  });

  it("calls onOpenSettings when the button is clicked", () => {
    const onOpenSettings = vi.fn();
    render(<NoModelHint hasModel={false} onOpenSettings={onOpenSettings} />);
    fireEvent.click(screen.getByRole("button", { name: /orchestrator\.open_settings/i }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
  });

  it("renders nothing when hasModel is true", () => {
    const { container } = render(
      <NoModelHint hasModel={true} onOpenSettings={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });
});
