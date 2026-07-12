/**
 * Provider-P4 — per-row connectivity status dot in ProviderConfigList.
 *
 * Dot = level-1 connectivity (tri-state from POST /provider-configs/{id}/health);
 * the existing test button stays level-2 (real chat test). Auto-probe fires ONCE
 * on mount and ONLY for rows never probed or probed >5min ago (spec D4: no polling).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// ── i18n mock ──────────────────────────────────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// ── api mock ───────────────────────────────────────────────────────────────────
const mockProbeProviderHealth = vi.fn();
const mockFetchProviderModels = vi.fn().mockResolvedValue({
  models: [],
  fetched_at: null,
  stale: false,
  error: null,
  source: "static",
});

vi.mock("../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
    getAccessToken: vi.fn().mockResolvedValue({ token_required: false, token: null }),
  },
  API_BASE: "",
  addProviderConfig: vi.fn().mockResolvedValue({}),
  updateProviderConfig: vi.fn().mockResolvedValue({}),
  setPrimaryProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  deleteProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
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
  { key: "deepseek", label: "DeepSeek", base_url: "", default_model: "deepseek-chat", native: false, models: ["deepseek-chat"] },
];

/** Fresh probe timestamp (1 min ago) — auto-probe must SKIP this row. */
const freshIso = () => new Date(Date.now() - 60_000).toISOString();
/** Stale probe timestamp (10 min ago, past the 5-min cutoff) — auto-probe fires. */
const staleIso = () => new Date(Date.now() - 10 * 60_000).toISOString();

function cfg(over: Partial<ProviderConfig>): ProviderConfig {
  return {
    id: 1,
    label: "A",
    provider: "deepseek",
    model: "deepseek-chat",
    base_url: "",
    api_key: "de...cd",
    is_primary: false,
    last_health: null,
    last_health_at: null,
    ...over,
  };
}

function renderList(configs: ProviderConfig[], ui?: (el: React.ReactElement) => React.ReactElement) {
  const el = (
    <ProviderConfigList
      llmProviders={providers}
      providerConfigs={configs}
      onConfigsChange={vi.fn()}
    />
  );
  return render(ui ? ui(el) : el);
}

beforeEach(() => {
  mockProbeProviderHealth.mockReset();
  mockProbeProviderHealth.mockResolvedValue({
    state: "reachable_models",
    latency_ms: 12,
    detail: null,
    last_health_at: new Date().toISOString(),
  });
});

describe("health status dot", () => {
  it("renders per-state colors and tooltips", () => {
    const configs = [
      cfg({ id: 1, last_health: "reachable_models", last_health_at: freshIso(), is_primary: true }),
      cfg({ id: 2, last_health: "reachable_no_list", last_health_at: freshIso() }),
      cfg({ id: 3, last_health: "unreachable", last_health_at: freshIso() }),
      cfg({ id: 4, last_health: null, last_health_at: freshIso() }),
    ];
    renderList(configs);
    const dot = (i: number) => screen.getByTestId(`provider-health-dot-${i}`);
    expect(dot(0)).toHaveAttribute("data-health-state", "reachable_models");
    expect(dot(0).className).toContain("text-success");
    expect(dot(1)).toHaveAttribute("data-health-state", "reachable_no_list");
    expect(dot(1).className).toContain("text-warning");
    expect(dot(1)).toHaveAttribute("title", "settings.healthDotNoList");
    expect(dot(2)).toHaveAttribute("data-health-state", "unreachable");
    expect(dot(2).className).toContain("text-danger");
    expect(dot(3)).toHaveAttribute("data-health-state", "unknown");
    expect(dot(3).textContent).toBe("○"); // hollow = never probed
    // all rows were freshly probed → no auto-probe
    expect(mockProbeProviderHealth).not.toHaveBeenCalled();
  });

  it("shows relative time next to the dot when a probe timestamp exists", () => {
    renderList([cfg({ id: 1, last_health: "reachable_models", last_health_at: freshIso() })]);
    // The selected config surfaces its relative time in BOTH the master-list dot
    // and the detail-pane ConnectionTester (Task 3) — at least one is present.
    expect(screen.getAllByText("settings.timeMinutesAgo").length).toBeGreaterThanOrEqual(1);
  });

  it("click fires a manual probe and updates the dot state", async () => {
    renderList([cfg({ id: 7, last_health: "unreachable", last_health_at: freshIso() })]);
    expect(mockProbeProviderHealth).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("provider-health-dot-0"));
    await waitFor(() => expect(mockProbeProviderHealth).toHaveBeenCalledWith(7));
    await waitFor(() =>
      expect(screen.getByTestId("provider-health-dot-0")).toHaveAttribute(
        "data-health-state", "reachable_models"));
  });

  it("auto-probes on mount ONLY stale or never-probed rows", async () => {
    const configs = [
      cfg({ id: 1, last_health: "reachable_models", last_health_at: freshIso(), is_primary: true }),
      cfg({ id: 2, last_health: "reachable_models", last_health_at: staleIso() }),
      cfg({ id: 3, last_health: null, last_health_at: null }),
    ];
    renderList(configs);
    await waitFor(() => expect(mockProbeProviderHealth).toHaveBeenCalledTimes(2));
    const ids = mockProbeProviderHealth.mock.calls.map((c) => c[0]).sort();
    expect(ids).toEqual([2, 3]);
    // settle — no further probes (no polling)
    await new Promise((r) => setTimeout(r, 20));
    expect(mockProbeProviderHealth).toHaveBeenCalledTimes(2);
  });

  it("StrictMode double-mount does not double-probe", async () => {
    renderList(
      [cfg({ id: 5, last_health: null, last_health_at: null })],
      (el) => <React.StrictMode>{el}</React.StrictMode>,
    );
    await waitFor(() => expect(mockProbeProviderHealth).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(mockProbeProviderHealth).toHaveBeenCalledTimes(1);
  });
});
