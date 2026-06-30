/**
 * B5 frontend tests: suggest-primary button + capability table in ProviderConfigList.
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
const mockGetCatalog = vi.fn();

vi.mock("../api/client", () => ({
  suggestPrimary: (...args: unknown[]) => mockSuggestPrimary(...args),
  setPrimaryProviderConfig: (...args: unknown[]) => mockSetPrimaryProviderConfig(...args),
  getCatalog: (...args: unknown[]) => mockGetCatalog(...args),
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
    mockGetCatalog.mockReset();
    // default: catalog returns empty (to avoid unrelated rendering issues)
    mockGetCatalog.mockResolvedValue([]);
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

describe("B5: capability table", () => {
  beforeEach(() => {
    mockSuggestPrimary.mockReset();
    mockGetCatalog.mockReset();
  });

  it("renders a collapsible capability table toggle", async () => {
    mockGetCatalog.mockResolvedValue([
      {
        provider: "anthropic",
        capabilities: { cost: 3, speed: 6, tool_calling: 9, reasoning: 10, long_context: 9 },
        languages: { en: 10, zh: 8 },
      },
    ]);
    renderComponent();

    await waitFor(() => {
      expect(
        screen.getByTestId("capability-table-toggle"),
      ).toBeInTheDocument();
    });
  });

  it("shows provider capability data inside the table after clicking the toggle", async () => {
    mockGetCatalog.mockResolvedValue([
      {
        provider: "anthropic",
        capabilities: { cost: 3, speed: 6, tool_calling: 9, reasoning: 10, long_context: 9 },
        languages: { en: 10, zh: 8 },
      },
    ]);
    renderComponent();

    // Wait for the toggle button to appear (catalog loaded)
    await waitFor(() => screen.getByTestId("capability-table-toggle"));
    const toggle = screen.getByTestId("capability-table-toggle");
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(screen.getByText("anthropic")).toBeInTheDocument();
    });
  });
});

