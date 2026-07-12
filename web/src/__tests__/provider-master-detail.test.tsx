/**
 * Settings Task 2 — ProviderConfigList master-detail split.
 *
 * These tests pin the master-detail STRUCTURE introduced when the 42K
 * single-component was split into ProviderMasterList + ProviderDetailPane:
 * selecting a master row shows that config's detail; "+ add" enters a draft
 * whose blank form renders in the detail pane; deleting the selected row moves
 * selection to a survivor. Behavior-equivalence of the field-level flows
 * (blur-save, cache invalidation, health, custom, keyless draft, …) is covered
 * by settings-providers.test.tsx.
 */

import React, { useState } from "react";
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

// ── api mock ───────────────────────────────────────────────────────────────────
const mockAddProviderConfig = vi.fn().mockResolvedValue({
  id: 3, label: "C", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "", is_primary: false,
});
const mockDeleteProviderConfig = vi.fn().mockResolvedValue({ ok: true });
const mockFetchProviderModels = vi.fn().mockResolvedValue({
  models: [], fetched_at: null, stale: false, error: null, source: "static",
});
const mockProbeProviderHealth = vi.fn().mockResolvedValue({
  state: "reachable_models", latency_ms: 1, detail: null, last_health_at: "2026-07-12T00:00:00",
});

vi.mock("../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
    getAccessToken: vi.fn().mockResolvedValue({ token_required: false, token: null }),
  },
  API_BASE: "",
  addProviderConfig: (...args: unknown[]) => mockAddProviderConfig(...args),
  updateProviderConfig: vi.fn().mockResolvedValue({}),
  setPrimaryProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  deleteProviderConfig: (...args: unknown[]) => mockDeleteProviderConfig(...args),
  fetchProviderModels: (...args: unknown[]) => mockFetchProviderModels(...args),
  suggestPrimary: vi.fn().mockResolvedValue(null),
  getCatalog: vi.fn().mockResolvedValue([]),
  testLlm: vi.fn().mockResolvedValue({ ok: true }),
  testProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  probeProviderHealth: (...args: unknown[]) => mockProbeProviderHealth(...args),
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: Object.assign(
    (sel: (s: { token: string; setToken: (t: string) => void }) => unknown) =>
      sel({ token: "", setToken: () => {} }),
    { getState: () => ({ token: "", setToken: () => {} }) },
  ),
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

describe("provider master-detail structure", () => {
  it("renders a master row per config with model id + primary star", () => {
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    expect(screen.getByTestId("provider-master-row-0")).toBeInTheDocument();
    expect(screen.getByTestId("provider-master-row-1")).toBeInTheDocument();
    // model ids visible in the list
    expect(screen.getByText("deepseek-chat")).toBeInTheDocument();
    expect(screen.getByText("qwen-max")).toBeInTheDocument();
    // exactly one primary star (the primary config)
    expect(screen.getByText("★")).toBeInTheDocument();
  });

  it("selects the primary config by default and shows its detail", () => {
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    expect(screen.getByTestId("provider-master-row-0")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("provider-master-row-1")).toHaveAttribute("data-selected", "false");
    // detail pane reflects the selected (primary) config
    const model = screen.getByTestId("provider-config-model-0") as HTMLInputElement;
    expect(model.value).toBe("deepseek-chat");
    // the non-selected config's detail field is NOT mounted
    expect(screen.queryByTestId("provider-config-model-1")).toBeNull();
  });

  it("clicking a master row selects it and swaps the detail pane", async () => {
    const user = userEvent.setup();
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    await user.click(screen.getByTestId("provider-master-row-1"));
    expect(screen.getByTestId("provider-master-row-1")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("provider-master-row-0")).toHaveAttribute("data-selected", "false");
    const model = screen.getByTestId("provider-config-model-1") as HTMLInputElement;
    expect(model.value).toBe("qwen-max");
    expect(screen.queryByTestId("provider-config-model-0")).toBeNull();
  });

  it("'+ add' enters a draft whose blank form renders in the detail pane", async () => {
    const user = userEvent.setup();
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    // No draft form initially
    expect(screen.queryByTestId("provider-draft-model")).toBeNull();
    await user.click(screen.getByRole("button", { name: /btnAddModel/i }));
    // Draft form appears in the detail pane; a pending row shows in the master list
    expect(screen.getByTestId("provider-draft-model")).toBeInTheDocument();
    expect(screen.getByTestId("provider-master-draft-row")).toBeInTheDocument();
    // The draft seeds from the first provider (deepseek)
    expect((screen.getByTestId("provider-draft-model") as HTMLInputElement).value).toBe("deepseek-chat");
    // Cancel returns to the selected config's detail
    await user.click(screen.getByRole("button", { name: /common\.cancel/i }));
    expect(screen.queryByTestId("provider-draft-model")).toBeNull();
    expect(screen.getByTestId("provider-config-model-0")).toBeInTheDocument();
  });

  it("deleting the selected row moves selection to a survivor", async () => {
    const user = userEvent.setup();
    mockDeleteProviderConfig.mockResolvedValue({ ok: true });
    function Harness() {
      const [cfgs, setCfgs] = useState<ProviderConfig[]>(configs);
      return (
        <ProviderConfigList llmProviders={providers} providerConfigs={cfgs} onConfigsChange={setCfgs} />
      );
    }
    render(<Harness />);
    // Select the non-primary row (id 2) — its detail delete button is enabled
    await user.click(screen.getByTestId("provider-master-row-1"));
    expect(screen.getByTestId("provider-config-model-1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "settings.btnDelete" }));
    // The row is gone and selection re-anchors to the surviving primary config
    await waitFor(() => expect(screen.queryByTestId("provider-master-row-1")).toBeNull());
    expect(mockDeleteProviderConfig).toHaveBeenCalledWith(2);
    expect(screen.getByTestId("provider-master-row-0")).toHaveAttribute("data-selected", "true");
    // Detail now reflects the survivor
    expect((screen.getByTestId("provider-config-model-0") as HTMLInputElement).value).toBe("deepseek-chat");
  });

  it("renders the detail empty state when there are no configs and no draft", () => {
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={[]} onConfigsChange={vi.fn()} />,
    );
    expect(screen.getByTestId("provider-detail-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("provider-detail-pane")).toBeNull();
    // The add button is still available in the master list
    expect(screen.getByRole("button", { name: /btnAddModel/i })).toBeInTheDocument();
  });
});
