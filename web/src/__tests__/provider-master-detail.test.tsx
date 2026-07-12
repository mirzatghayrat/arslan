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

  // FIX 1 — health dot must be a SIBLING of the row-select control, not nested
  // inside an interactive element (axe nested-interactive), and both must be
  // independently keyboard-activatable.
  it("health dot and row-select are independent keyboard-activatable siblings (no nested interactive)", async () => {
    const user = userEvent.setup();
    const fresh = new Date(Date.now() - 60_000).toISOString();
    // Fresh probe timestamps → the mount auto-probe skips these rows, so the
    // dot is not mid-probe when we exercise manual keyboard activation.
    const healthyConfigs: ProviderConfig[] = configs.map((c) => ({
      ...c,
      last_health: "reachable_models",
      last_health_at: fresh,
    }));
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={healthyConfigs} onConfigsChange={vi.fn()} />,
    );

    const dot = screen.getByTestId("provider-health-dot-0");
    const rowSelect = screen.getByTestId("provider-master-row-0");

    // (a) the dot button is NOT a descendant of the row-select control …
    expect(rowSelect.contains(dot)).toBe(false);
    // … and has no interactive (button / role=button) ancestor at all.
    for (let el = dot.parentElement; el && el !== document.body; el = el.parentElement) {
      expect(el.getAttribute("role")).not.toBe("button");
      expect(el.tagName).not.toBe("BUTTON");
    }

    // (b) keyboard-activate the health dot → probe fires (not swallowed).
    mockProbeProviderHealth.mockClear();
    dot.focus();
    expect(document.activeElement).toBe(dot);
    await user.keyboard("{Enter}");
    await waitFor(() => expect(mockProbeProviderHealth).toHaveBeenCalledWith(1));

    // (c) keyboard-activate the row-select for row 1 → selection moves there.
    const rowSelect1 = screen.getByTestId("provider-master-row-1");
    rowSelect1.focus();
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(rowSelect1).toHaveAttribute("data-selected", "true"),
    );
  });

  // FIX 2 — deleting the selected row must land on the survivor in the SAME
  // render (selection set inside handleDelete), so the detail pane never flashes
  // its empty state before re-anchoring.
  it("deleting the selected row lands on the survivor with no empty-state flash", async () => {
    const user = userEvent.setup();
    mockDeleteProviderConfig.mockResolvedValue({ ok: true });

    let emptyFlashSeen = false;
    const sawEmpty = (el: HTMLElement) =>
      el.matches('[data-testid="provider-detail-empty"]') ||
      !!el.querySelector('[data-testid="provider-detail-empty"]');
    const observer = new MutationObserver((records) => {
      for (const rec of records) {
        // A fresh empty node mounted …
        rec.addedNodes.forEach((n) => {
          if (n instanceof HTMLElement && sawEmpty(n)) emptyFlashSeen = true;
        });
        // … OR React reused the detail <div> and flipped its data-testid to the
        // empty marker (the flash we're actually guarding against).
        if (
          rec.type === 'attributes' &&
          rec.target instanceof HTMLElement &&
          rec.target.getAttribute('data-testid') === 'provider-detail-empty'
        ) {
          emptyFlashSeen = true;
        }
      }
    });

    function Harness() {
      const [cfgs, setCfgs] = useState<ProviderConfig[]>(configs);
      return (
        <ProviderConfigList llmProviders={providers} providerConfigs={cfgs} onConfigsChange={setCfgs} />
      );
    }
    render(<Harness />);

    // Select the non-primary row (id 2) so its detail delete button is enabled.
    await user.click(screen.getByTestId("provider-master-row-1"));
    expect(screen.getByTestId("provider-config-model-1")).toBeInTheDocument();

    // Watch for any provider-detail-empty node appearing across the delete.
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-testid"],
    });
    await user.click(screen.getByRole("button", { name: "settings.btnDelete" }));
    await waitFor(() => expect(screen.queryByTestId("provider-master-row-1")).toBeNull());
    // Flush any queued mutation records before disconnecting.
    await Promise.resolve();
    observer.disconnect();

    expect(mockDeleteProviderConfig).toHaveBeenCalledWith(2);
    // No empty-state flash — the detail re-anchored to the survivor in one paint.
    expect(emptyFlashSeen).toBe(false);
    expect(screen.queryByTestId("provider-detail-empty")).toBeNull();
    expect(screen.getByTestId("provider-master-row-0")).toHaveAttribute("data-selected", "true");
    expect((screen.getByTestId("provider-config-model-0") as HTMLInputElement).value).toBe(
      "deepseek-chat",
    );
  });
});
