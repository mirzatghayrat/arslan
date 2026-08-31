/**
 * ProviderConfigList — one card per model, selected card expands inline.
 *
 * This replaced a left master list + right detail pane. The behaviours pinned
 * here outlived that structure and are what actually matter: a row per config
 * with its model id and primary star; selecting one reveals its fields;
 * "+ add" opens a blank draft; deleting the selected row lands on a survivor
 * without flashing an empty state. Field-level flows (blur-save, cache
 * invalidation, custom provider, keyless draft, …) are covered by
 * settings-providers.test.tsx.
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
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: Object.assign(
    (sel: (s: { token: string; setToken: (t: string) => void }) => unknown) =>
      sel({ token: "", setToken: () => {} }),
    { getState: () => ({ token: "", setToken: () => {} }) },
  ),
}));

import ProviderConfigList from "../components/ProviderConfigList";
import { capabilityOverrideKey } from "../components/settings/CapabilityBadges";
import type { ProviderOption, ProviderConfig } from "../api/client.types";

const providers: ProviderOption[] = [
  { key: "deepseek", label: "DeepSeek", base_url: "", default_model: "deepseek-chat", native: false, models: ["deepseek-chat", "deepseek-reasoner"] },
  { key: "qwen", label: "Qwen", base_url: "", default_model: "qwen-max", native: false, models: ["qwen-max", "qwen-plus"] },
];

const configs: ProviderConfig[] = [
  { id: 1, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "de...cd", is_primary: true },
  { id: 2, label: "B", provider: "qwen", model: "qwen-max", base_url: "", api_key: "qw...ef", is_primary: false },
];

describe("provider card list", () => {
  it("renders a card per config with model id + primary star", () => {
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    expect(screen.getByTestId("provider-card-row-0")).toBeInTheDocument();
    expect(screen.getByTestId("provider-card-row-1")).toBeInTheDocument();
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
    expect(screen.getByTestId("provider-card-row-0")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("provider-card-row-1")).toHaveAttribute("data-selected", "false");
    // detail pane reflects the selected (primary) config
    const model = screen.getByTestId("provider-config-model-0") as HTMLInputElement;
    expect(model.value).toBe("deepseek-chat");
    // the non-selected config's detail field is NOT mounted
    expect(screen.queryByTestId("provider-config-model-1")).toBeNull();
  });

  it("clicking a card selects it and reveals its fields", async () => {
    const user = userEvent.setup();
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    await user.click(screen.getByTestId("provider-card-row-1"));
    expect(screen.getByTestId("provider-card-row-1")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("provider-card-row-0")).toHaveAttribute("data-selected", "false");
    const model = screen.getByTestId("provider-config-model-1") as HTMLInputElement;
    expect(model.value).toBe("qwen-max");
    expect(screen.queryByTestId("provider-config-model-0")).toBeNull();
  });

  it("'+ add' enters a draft whose blank form renders as its own card", async () => {
    const user = userEvent.setup();
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    // No draft form initially
    expect(screen.queryByTestId("provider-draft-model")).toBeNull();
    await user.click(screen.getByRole("button", { name: /btnAddModel/i }));
    // The blank draft form is its own card at the end of the list.
    expect(screen.getByTestId("provider-draft-model")).toBeInTheDocument();
    expect(screen.getByTestId("provider-draft-card")).toBeInTheDocument();
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
    await user.click(screen.getByTestId("provider-card-row-1"));
    expect(screen.getByTestId("provider-config-model-1")).toBeInTheDocument();
    await user.click(screen.getByTestId("provider-config-more-1"));
    await user.click(screen.getByTestId("provider-config-delete-1"));
    // The row is gone and selection re-anchors to the surviving primary config
    await waitFor(() => expect(screen.queryByTestId("provider-card-row-1")).toBeNull());
    expect(mockDeleteProviderConfig).toHaveBeenCalledWith(2);
    expect(screen.getByTestId("provider-card-row-0")).toHaveAttribute("data-selected", "true");
    // Detail now reflects the survivor
    expect((screen.getByTestId("provider-config-model-0") as HTMLInputElement).value).toBe("deepseek-chat");
  });

  it("purges stored capability overrides when its config is deleted (PK-reuse safety)", async () => {
    const user = userEvent.setup();
    mockDeleteProviderConfig.mockResolvedValue({ ok: true });
    // Config id 2 / model qwen-max has a manual capability override on disk.
    localStorage.setItem(capabilityOverrideKey(2, "qwen-max", "tools"), "on");
    function Harness() {
      const [cfgs, setCfgs] = useState<ProviderConfig[]>(configs);
      return (
        <ProviderConfigList llmProviders={providers} providerConfigs={cfgs} onConfigsChange={setCfgs} />
      );
    }
    render(<Harness />);
    await user.click(screen.getByTestId("provider-card-row-1"));
    await user.click(screen.getByTestId("provider-config-more-1"));
    await user.click(screen.getByTestId("provider-config-delete-1"));
    await waitFor(() => expect(mockDeleteProviderConfig).toHaveBeenCalledWith(2));
    // The override for the deleted id is purged so a future config reusing id 2
    // can't silently inherit it (SQLite reuses integer PKs).
    expect(localStorage.getItem(capabilityOverrideKey(2, "qwen-max", "tools"))).toBeNull();
  });

  it("offers only \"add a model\" when there are no configs and no draft", () => {
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={[]} onConfigsChange={vi.fn()} />,
    );
    // No cards, no fields, no draft — just the one thing worth doing. The old
    // layout showed a placeholder in the right-hand pane; without that pane the
    // add button IS the empty state.
    expect(screen.queryByTestId("provider-card-0")).toBeNull();
    expect(screen.queryByTestId("provider-config-model-0")).toBeNull();
    expect(screen.queryByTestId("provider-draft-card")).toBeNull();
    expect(screen.getByTestId("provider-add-model")).toBeInTheDocument();
  });

  // FIX 1 — health dot must be a SIBLING of the row-select control, not nested
  // inside an interactive element (axe nested-interactive), and both must be
  // independently keyboard-activatable.
  it("a card row is ONE control with nothing interactive inside it", async () => {
    const user = userEvent.setup();
    // The old layout put a clickable health dot next to the row-select button
    // and had to keep them as non-nested siblings so neither swallowed the
    // other's activation. The dot is gone — status is not something you click
    // to discover any more — so the row can be a single button, which makes
    // nested-interactive structurally impossible rather than merely avoided.
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );

    const row = screen.getByTestId("provider-card-row-0");
    expect(row.tagName).toBe("BUTTON");
    expect(row.querySelectorAll('button, a, input, select, textarea, [role="button"]')).toHaveLength(0);

    // Keyboard-activating a row selects it — the property the sibling dance
    // existed to protect.
    const row1 = screen.getByTestId("provider-card-row-1");
    row1.focus();
    expect(document.activeElement).toBe(row1);
    await user.keyboard("{Enter}");
    await waitFor(() => expect(row1).toHaveAttribute("data-selected", "true"));
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
    await user.click(screen.getByTestId("provider-card-row-1"));
    expect(screen.getByTestId("provider-config-model-1")).toBeInTheDocument();

    // Watch for any provider-detail-empty node appearing across the delete.
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-testid"],
    });
    await user.click(screen.getByTestId("provider-config-more-1"));
    await user.click(screen.getByTestId("provider-config-delete-1"));
    await waitFor(() => expect(screen.queryByTestId("provider-card-row-1")).toBeNull());
    // Flush any queued mutation records before disconnecting.
    await Promise.resolve();
    observer.disconnect();

    expect(mockDeleteProviderConfig).toHaveBeenCalledWith(2);
    // No empty-state flash — the detail re-anchored to the survivor in one paint.
    expect(emptyFlashSeen).toBe(false);
    expect(screen.queryByTestId("provider-detail-empty")).toBeNull();
    expect(screen.getByTestId("provider-card-row-0")).toHaveAttribute("data-selected", "true");
    expect((screen.getByTestId("provider-config-model-0") as HTMLInputElement).value).toBe(
      "deepseek-chat",
    );
  });
});
