/**
 * Task A9 — Settings multi-config list + strategy dropdown.
 *
 * Tests the ProviderConfigList presentational child component extracted from
 * SettingsScreen. This keeps the test clean and the component focused.
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── i18n mock ──────────────────────────────────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// ── api mock (ProviderConfigList calls client functions directly) ───────────────
const mockAddProviderConfig = vi.fn().mockResolvedValue({ id: 3, label: "C", provider: "deepseek", model: "deepseek-reasoner", base_url: "", api_key: "", is_primary: false });
const mockUpdateProviderConfig = vi.fn().mockResolvedValue({});
const mockSetPrimaryProviderConfig = vi.fn().mockResolvedValue({ ok: true });
const mockDeleteProviderConfig = vi.fn().mockResolvedValue({ ok: true });

vi.mock("../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
  },
  API_BASE: "",
  addProviderConfig: (...args: unknown[]) => mockAddProviderConfig(...args),
  updateProviderConfig: (...args: unknown[]) => mockUpdateProviderConfig(...args),
  setPrimaryProviderConfig: (...args: unknown[]) => mockSetPrimaryProviderConfig(...args),
  deleteProviderConfig: (...args: unknown[]) => mockDeleteProviderConfig(...args),
  suggestPrimary: vi.fn().mockResolvedValue(null),
  getCatalog: vi.fn().mockResolvedValue([]),
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: null }) },
}));

import ProviderConfigList from "../components/ProviderConfigList";
import type { ProviderOption, ProviderConfig } from "../api/client.types";

const providers: ProviderOption[] = [
  { key: "deepseek", label: "DeepSeek", base_url: "", default_model: "deepseek-chat", native: false, models: ["deepseek-chat", "deepseek-reasoner"] },
  { key: "qwen", label: "Qwen", base_url: "", default_model: "qwen-max", native: false, models: ["qwen-max", "qwen-plus"] },
];

const configs: ProviderConfig[] = [
  { id: 1, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "de...cd", is_primary: true },
  { id: 2, label: "B", provider: "qwen", model: "qwen-max", base_url: "", api_key: "qw...ef", is_primary: false },
];

describe("ProviderConfigList", () => {
  it("renders configured rows with provider model visible", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // Custom Select triggers: open the model select for the first row by id
    const modelTrigger0 = document.getElementById("provider-config-model-0") as HTMLButtonElement;
    expect(modelTrigger0).not.toBeNull();
    // The trigger shows the selected model label in its text
    expect(modelTrigger0.textContent).toContain("deepseek-chat");
    const modelTrigger1 = document.getElementById("provider-config-model-1") as HTMLButtonElement;
    expect(modelTrigger1).not.toBeNull();
    expect(modelTrigger1.textContent).toContain("qwen-max");
  });

  it("shows a set-primary button for non-primary rows", () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // At least one "Set primary" control for the non-primary row
    expect(screen.getAllByRole("button", { name: /primary/i }).length).toBeGreaterThan(0);
  });

  it("marks the primary row with a star indicator", () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // The primary row should show a ★ character
    expect(screen.getByText("★")).toBeInTheDocument();
  });

  it("shows an Add model button", () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // The i18n mock returns the key; the key ends with "btnAddModel"
    expect(screen.getByRole("button", { name: /btnAddModel/i })).toBeInTheDocument();
  });

  it("calls setPrimaryProviderConfig when set-primary is clicked", async () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    const setPrimaryBtns = screen.getAllByRole("button", { name: /primary/i });
    fireEvent.click(setPrimaryBtns[0]);
    // Wait a tick for async
    await new Promise((r) => setTimeout(r, 0));
    expect(mockSetPrimaryProviderConfig).toHaveBeenCalledWith(2);
  });

  it("renders model options from the selected provider's models array", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // Open the model select for the first (deepseek) row
    const modelTrigger0 = document.getElementById("provider-config-model-0") as HTMLButtonElement;
    await user.click(modelTrigger0);
    // Both model options should be rendered in the listbox
    const options = screen.getAllByRole("option").map((o) => o.textContent?.trim());
    expect(options).toContain("deepseek-chat");
    expect(options).toContain("deepseek-reasoner");
  });

  it("renders a strategy dropdown with 4 options", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );
    // Custom Select: trigger is a button with id "provider-strategy-select"
    const strategyTrigger = document.getElementById("provider-strategy-select") as HTMLButtonElement;
    await user.click(strategyTrigger);
    // All 4 strategy options should appear in the listbox
    const options = screen.getAllByRole("option").map((o) => o.getAttribute("data-value") ?? o.textContent?.trim());
    // Check via text content matching i18n key
    const optionTexts = screen.getAllByRole("option").map((o) => o.textContent?.trim());
    expect(optionTexts.some((t) => /single/i.test(t ?? ""))).toBe(true);
    expect(optionTexts.some((t) => /cost/i.test(t ?? ""))).toBe(true);
    expect(optionTexts.some((t) => /balanced/i.test(t ?? ""))).toBe(true);
    expect(optionTexts.some((t) => /performance/i.test(t ?? ""))).toBe(true);
  });

  it("calls onStrategyChange when strategy option is clicked", async () => {
    const user = userEvent.setup();
    const onStrategyChange = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={onStrategyChange}
      />
    );
    // Open the strategy custom select
    const strategyTrigger = document.getElementById("provider-strategy-select") as HTMLButtonElement;
    await user.click(strategyTrigger);
    // Click "balanced" option (2 configs so not disabled)
    const balancedOpt = screen.getAllByRole("option").find((o) =>
      /balanced/i.test(o.textContent ?? ""),
    );
    expect(balancedOpt).toBeTruthy();
    await user.click(balancedOpt!);
    expect(onStrategyChange).toHaveBeenCalledWith("balanced");
  });
});
