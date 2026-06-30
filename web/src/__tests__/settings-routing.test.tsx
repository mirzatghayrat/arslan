/**
 * B5 frontend tests: suggest-primary button in ProviderConfigList.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: null }) },
}));

const mockSuggestPrimary = vi.fn();
const mockSetPrimaryProviderConfig = vi.fn();

vi.mock("../api/client", () => ({
  suggestPrimary: (...args: unknown[]) => mockSuggestPrimary(...args),
  setPrimaryProviderConfig: (...args: unknown[]) => mockSetPrimaryProviderConfig(...args),
  addProviderConfig: vi.fn().mockResolvedValue({}),
  updateProviderConfig: vi.fn().mockResolvedValue({}),
  deleteProviderConfig: vi.fn().mockResolvedValue({}),
  API_BASE: "",
}));

import ProviderConfigList from "../components/ProviderConfigList";
import type { ProviderConfig, ProviderOption } from "../api/client.types";

const providers: ProviderOption[] = [
  {
    key: "anthropic",
    label: "Anthropic",
    base_url: "https://api.anthropic.com",
    default_model: "claude-sonnet-4-6",
    native: true,
    models: ["claude-opus-4-8", "claude-sonnet-4-6"],
  },
];

const configs: ProviderConfig[] = [
  {
    id: 1,
    label: "Anthropic",
    provider: "anthropic",
    model: "claude-sonnet-4-6",
    base_url: "https://api.anthropic.com",
    api_key: "sk-ant-••••",
    is_primary: true,
  },
];

function renderComponent(overrideConfigs = configs) {
  const onConfigsChange = vi.fn();
  render(
    <ProviderConfigList
      llmProviders={providers}
      providerConfigs={overrideConfigs}
      onConfigsChange={onConfigsChange}
      strategy="single"
      onStrategyChange={vi.fn()}
    />,
  );
  return { onConfigsChange };
}

describe("B5: suggest-primary button", () => {
  beforeEach(() => {
    mockSuggestPrimary.mockReset();
    mockSetPrimaryProviderConfig.mockReset();
  });

  it("renders a suggest-primary button", () => {
    renderComponent();
    expect(
      screen.getByRole("button", { name: /settings\.btnSuggestPrimary/i }),
    ).toBeInTheDocument();
  });

  it("shows the recommendation rationale after clicking suggest-primary", async () => {
    mockSuggestPrimary.mockResolvedValue({
      id: 1,
      provider: "anthropic",
      rationale: "Best all-round quality",
    });
    renderComponent();

    const btn = screen.getByRole("button", { name: /settings\.btnSuggestPrimary/i });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(screen.getByText("Best all-round quality")).toBeInTheDocument();
    });
  });

  it("clicking Use this calls setPrimaryProviderConfig with the suggested id", async () => {
    mockSuggestPrimary.mockResolvedValue({
      id: 2,
      provider: "anthropic",
      rationale: "Cheapest option",
    });
    mockSetPrimaryProviderConfig.mockResolvedValue({ ok: true });

    renderComponent();
    fireEvent.click(screen.getByRole("button", { name: /settings\.btnSuggestPrimary/i }));

    await waitFor(() => screen.getByText("Cheapest option"));

    fireEvent.click(screen.getByRole("button", { name: /settings\.btnUseThis/i }));

    await waitFor(() => {
      expect(mockSetPrimaryProviderConfig).toHaveBeenCalledWith(2);
    });
  });
});

