/**
 * Settings Task 3 — RoutingStrategyCard (extracted from ProviderConfigList).
 *
 * The strategy Select + Suggest-primary, lifted into their own card at the top
 * of the providers section. Behavior is UNCHANGED from the inline version:
 * single/cost/balanced/performance with ≥2-config gating, and the
 * Suggest-primary button + rationale panel.
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import RoutingStrategyCard from "../components/settings/RoutingStrategyCard";

describe("RoutingStrategyCard", () => {
  it("renders the four strategy options", async () => {
    const user = userEvent.setup();
    render(
      <RoutingStrategyCard
        strategy="single"
        onStrategyChange={vi.fn()}
        configCount={2}
      />,
    );
    const trigger = document.getElementById(
      "provider-strategy-select",
    ) as HTMLButtonElement;
    expect(trigger).not.toBeNull();
    await user.click(trigger);
    const texts = screen.getAllByRole("option").map((o) => o.textContent ?? "");
    expect(texts.some((t) => /single/i.test(t))).toBe(true);
    expect(texts.some((t) => /cost/i.test(t))).toBe(true);
    expect(texts.some((t) => /balanced/i.test(t))).toBe(true);
    expect(texts.some((t) => /performance/i.test(t))).toBe(true);
  });

  it("disables non-single options and shows the hint with <2 configs", async () => {
    const user = userEvent.setup();
    render(
      <RoutingStrategyCard
        strategy="single"
        onStrategyChange={vi.fn()}
        configCount={1}
      />,
    );
    expect(screen.getByText("settings.strategyHint")).toBeInTheDocument();
    await user.click(
      document.getElementById("provider-strategy-select") as HTMLButtonElement,
    );
    const options = screen.getAllByRole("option");
    const cost = options.find((o) => /cost/i.test(o.textContent ?? ""));
    const single = options.find((o) => /single/i.test(o.textContent ?? ""));
    expect(cost).toHaveAttribute("aria-disabled", "true");
    expect(single).not.toHaveAttribute("aria-disabled", "true");
  });

  it("enables all options and hides the hint with 2+ configs", async () => {
    const user = userEvent.setup();
    render(
      <RoutingStrategyCard
        strategy="balanced"
        onStrategyChange={vi.fn()}
        configCount={2}
      />,
    );
    expect(screen.queryByText("settings.strategyHint")).toBeNull();
    await user.click(
      document.getElementById("provider-strategy-select") as HTMLButtonElement,
    );
    const cost = screen
      .getAllByRole("option")
      .find((o) => /cost/i.test(o.textContent ?? ""));
    expect(cost).not.toHaveAttribute("aria-disabled", "true");
  });

  it("fires onStrategyChange when an enabled option is picked", async () => {
    const user = userEvent.setup();
    const onStrategyChange = vi.fn();
    render(
      <RoutingStrategyCard
        strategy="single"
        onStrategyChange={onStrategyChange}
        configCount={2}
      />,
    );
    await user.click(
      document.getElementById("provider-strategy-select") as HTMLButtonElement,
    );
    const balanced = screen
      .getAllByRole("option")
      .find((o) => /balanced/i.test(o.textContent ?? ""));
    await user.click(balanced!);
    expect(onStrategyChange).toHaveBeenCalledWith("balanced");
  });

  it("renders the Suggest-primary button and calls onSuggestPrimary", () => {
    const onSuggestPrimary = vi.fn();
    render(
      <RoutingStrategyCard
        strategy="single"
        onStrategyChange={vi.fn()}
        configCount={2}
        onSuggestPrimary={onSuggestPrimary}
      />,
    );
    const btn = screen.getByRole("button", {
      name: /settings\.btnSuggestPrimary/i,
    });
    fireEvent.click(btn);
    expect(onSuggestPrimary).toHaveBeenCalled();
  });

  it("shows the suggestion rationale and calls onUseThis", () => {
    const onUseThis = vi.fn();
    render(
      <RoutingStrategyCard
        strategy="single"
        onStrategyChange={vi.fn()}
        configCount={2}
        onSuggestPrimary={vi.fn()}
        suggestion={{ id: 2, provider: "qwen", rationale: "Cheapest option" }}
        onUseThis={onUseThis}
      />,
    );
    expect(screen.getByText("Cheapest option")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /settings\.btnUseThis/i }),
    );
    expect(onUseThis).toHaveBeenCalled();
  });
});
