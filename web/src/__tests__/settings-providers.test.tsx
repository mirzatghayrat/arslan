/**
 * Task A9 — Settings multi-config list + strategy dropdown.
 *
 * Tests the ProviderConfigList presentational child component extracted from
 * SettingsScreen. This keeps the test clean and the component focused.
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

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
  it("renders configured rows with provider model visible", () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // Both rows rendered — model values should be visible
    expect(screen.getByDisplayValue("deepseek-chat")).toBeInTheDocument();
    expect(screen.getByDisplayValue("qwen-max")).toBeInTheDocument();
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

  it("renders model options from the selected provider's models array", () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // The deepseek row should have both deepseek model options in its select
    const modelSelects = screen.getAllByTestId(/provider-config-model-/);
    const deepseekSelect = modelSelects[0] as HTMLSelectElement;
    const options = Array.from(deepseekSelect.options).map((o) => o.value);
    expect(options).toContain("deepseek-chat");
    expect(options).toContain("deepseek-reasoner");
  });

  it("renders a strategy dropdown with 4 options", () => {
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
    const strategySelect = screen.getByTestId("provider-strategy-select") as HTMLSelectElement;
    const options = Array.from(strategySelect.options).map((o) => o.value);
    expect(options).toContain("single");
    expect(options).toContain("cost");
    expect(options).toContain("balanced");
    expect(options).toContain("performance");
  });

  it("calls onStrategyChange when strategy dropdown changes", () => {
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
    const strategySelect = screen.getByTestId("provider-strategy-select");
    fireEvent.change(strategySelect, { target: { value: "balanced" } });
    expect(onStrategyChange).toHaveBeenCalledWith("balanced");
  });
});
