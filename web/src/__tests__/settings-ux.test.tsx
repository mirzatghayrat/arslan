/**
 * Task UX3 — Settings reflow: Test button, DOM ordering.
 *
 * TDD: these tests are written first and drive the implementation.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
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

vi.mock("../stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: null }) },
}));

// ── api mock ───────────────────────────────────────────────────────────────────
const mockTestLlm = vi.fn();
const mockTestProviderConfig = vi.fn();
const mockAddProviderConfig = vi.fn();
const mockUpdateProviderConfig = vi.fn();
const mockDeleteProviderConfig = vi.fn();
const mockSetPrimaryProviderConfig = vi.fn();

vi.mock("../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
  },
  API_BASE: "",
  previewProviderModels: vi.fn().mockResolvedValue({ models: [], fetched_at: null, stale: true, error: null, source: "static" }),
  addProviderConfig: (...args: unknown[]) => mockAddProviderConfig(...args),
  updateProviderConfig: (...args: unknown[]) => mockUpdateProviderConfig(...args),
  setPrimaryProviderConfig: (...args: unknown[]) => mockSetPrimaryProviderConfig(...args),
  deleteProviderConfig: (...args: unknown[]) => mockDeleteProviderConfig(...args),
  testLlm: (...args: unknown[]) => mockTestLlm(...args),
  testProviderConfig: (...args: unknown[]) => mockTestProviderConfig(...args),
  probeProviderHealth: vi.fn().mockResolvedValue({
    state: "reachable_models", latency_ms: 1, detail: null, last_health_at: "2026-07-12T00:00:00",
  }),
}));

import ProviderConfigList from "../components/ProviderConfigList";
import type { ProviderOption, ProviderConfig } from "../api/client.types";

/** MODEL1: Add model starts with no provider picked. */
function pickFirstProvider() {
  fireEvent.click(screen.getByLabelText("Provider"));
  fireEvent.pointerDown(screen.getAllByRole("option")[0]);
}

const providers: ProviderOption[] = [
  {
    key: "deepseek",
    label: "DeepSeek",
    base_url: "",
    default_model: "deepseek-chat",
    native: false,
    models: ["deepseek-chat", "deepseek-reasoner"],
  },
  {
    key: "qwen",
    label: "Qwen",
    base_url: "",
    default_model: "qwen-max",
    native: false,
    models: ["qwen-max", "qwen-plus"],
  },
];

const twoConfigs: ProviderConfig[] = [
  {
    id: 1,
    label: "A",
    provider: "deepseek",
    model: "deepseek-chat",
    base_url: "",
    api_key: "de...cd",
    is_primary: true,
  },
  {
    id: 2,
    label: "B",
    provider: "qwen",
    model: "qwen-max",
    base_url: "",
    api_key: "qw...ef",
    is_primary: false,
  },
];

const oneConfig: ProviderConfig[] = [twoConfigs[0]];

describe("settings clarity", () => {
  it("surfaces a failed default without silently selecting another provider or running a test", async () => {
    const user = userEvent.setup();
    render(<ProviderConfigList llmProviders={providers} providerConfigs={[
      { ...twoConfigs[0], last_health: "failed", last_health_detail: "Synthetic rejected credential" },
      { ...twoConfigs[1], last_health: "ok" },
    ]} onConfigsChange={vi.fn()} />);
    expect(screen.getByTestId("provider-primary-warning")).toHaveTextContent("settings.defaultNeedsAttention");
    await user.click(screen.getByTestId("provider-card-row-1"));
    await user.click(screen.getByTestId("provider-review-primary"));
    expect(screen.getByTestId("provider-card-row-0")).toHaveAttribute("aria-expanded", "true");
    expect(mockSetPrimaryProviderConfig).not.toHaveBeenCalled();
    expect(mockTestProviderConfig).not.toHaveBeenCalled();
  });

  it("keeps common fields visible and connection details collapsed without removing them", () => {
    render(<ProviderConfigList llmProviders={providers} providerConfigs={oneConfig} onConfigsChange={vi.fn()} />);
    const advanced = screen.getByTestId("provider-config-advanced-0");
    expect(advanced).not.toHaveAttribute("open");
    expect(advanced).toContainElement(screen.getByTestId("provider-config-baseurl-0"));
    expect(screen.getByTestId("provider-config-key-0")).toBeVisible();
    expect(screen.getByTestId("provider-config-model-0")).toBeVisible();
    expect(screen.getByText("settings.providerLabel")).toBeVisible();
    expect(screen.getByText("settings.modelLabel")).toBeVisible();
  });
});

beforeEach(() => {
  vi.clearAllMocks();
  mockAddProviderConfig.mockResolvedValue({
    id: 3,
    label: "C",
    provider: "deepseek",
    model: "deepseek-chat",
    base_url: "",
    api_key: "",
    is_primary: false,
  });
  mockUpdateProviderConfig.mockResolvedValue({});
  mockDeleteProviderConfig.mockResolvedValue({ ok: true });
  mockSetPrimaryProviderConfig.mockResolvedValue({ ok: true });
});

describe("(E) Test all batch button", () => {
  it("shows a single 'Test all' button when there are saved configs", () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
      />
    );

    expect(screen.getByTestId("provider-test-all")).toBeInTheDocument();
  });

  it("puts the one Test button on the selected card only", () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
      />
    );

    // The selected card carries the one Test button (there is no longer a
    // lesser "connection" test to distinguish it from). Collapsed cards carry
    // none — their status pill already says what the last test found, so a row
    // of buttons would just be noise.
    expect(screen.getByTestId("provider-config-test-0")).toBeInTheDocument();
    expect(screen.queryByTestId("provider-config-test-1")).toBeNull();
  });

  it("clicking Test all calls testProviderConfig for each config and shows ok indicators", async () => {
    mockTestProviderConfig.mockResolvedValue({ ok: true, latency_ms: 200 });

    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
      />
    );

    const testAllBtn = screen.getByTestId("provider-test-all");
    fireEvent.click(testAllBtn);

    await waitFor(() => {
      expect(mockTestProviderConfig).toHaveBeenCalledWith(1);
      expect(mockTestProviderConfig).toHaveBeenCalledWith(2);
    });

    await waitFor(() => {
      // Every card's pill flips to "working" — the one vocabulary, everywhere.
      expect(screen.getByTestId("provider-status-0")).toHaveAttribute("data-status", "ok");
      expect(screen.getByTestId("provider-status-1")).toHaveAttribute("data-status", "ok");
      expect(screen.getByTestId("provider-default-summary")).toHaveTextContent("settings.statusOk");
    });
  });

  it("shows failure indicators for failed tests after Test all", async () => {
    mockTestProviderConfig.mockResolvedValueOnce({ ok: false, error: "Invalid API key" });
    mockTestProviderConfig.mockResolvedValueOnce({ ok: true, latency_ms: 100 });

    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId("provider-test-all"));

    await waitFor(() => {
      // The reason is on the card itself, collapsed or not: someone scanning to
      // find out why nothing works should not have to open each one.
      expect(screen.getAllByText(/Invalid API key/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByTestId("provider-status-0")).toHaveAttribute("data-status", "failed");
      expect(screen.getByTestId("provider-default-summary")).toHaveTextContent("settings.statusFailed");
      expect(screen.getByText("settings.statusOk")).toBeInTheDocument();
    });
  });
});

// ── (F) Deep test surfaces the latency from testProviderConfig ───────────────

describe("(F) Test latency wiring", () => {
  it("clicking Test on the selected card shows the latency_ms from testProviderConfig", async () => {
    mockTestProviderConfig.mockResolvedValue({ ok: true, latency_ms: 150 });

    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
      />
    );

    // The primary config (id 1) is selected by default → its card's Test button
    // runs the one real chat round-trip.
    fireEvent.click(screen.getByTestId("provider-config-test-0"));

    await waitFor(() => {
      expect(mockTestProviderConfig).toHaveBeenCalledWith(1);
      expect(screen.getByText(/· 150ms/)).toBeInTheDocument();
    });
  });
});

// ── (E) Draft / add-new flow: Add enabled when fields filled (no test gate) ──

describe("(E) Draft config: Add enabled when fields are filled", () => {
  it("Add button is enabled with an empty api_key (P3 FIX 1: keyless local servers)", async () => {
    // D3/B3: api_key is OPTIONAL — keyless configs (ollama, LM Studio, vLLM)
    // are legitimate and the draft is their only UI entry point. The backend
    // accepts empty keys everywhere (empty key = no Authorization header).
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
      />
    );

    // Open draft form and pick a provider: its model is filled from the defaults
    fireEvent.click(screen.getByRole("button", { name: /btnAddModel/i }));
    pickFirstProvider();

    // Confirm must NOT be gated on the (empty) api_key
    await waitFor(() => {
      expect(screen.getByTestId("provider-draft-confirm")).not.toBeDisabled();
    });
  });

  it("Add button is enabled once provider + model + api_key are non-empty (no test required)", async () => {
    const user = userEvent.setup();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
      />
    );

    // Open draft form
    fireEvent.click(screen.getByRole("button", { name: /btnAddModel/i }));
    pickFirstProvider();

    // Type an api_key — the picked provider's model is filled from the defaults
    const keyInput = await screen.findByPlaceholderText("settings.labelConfigApiKey");
    await user.type(keyInput, "sk-test-key");

    // Confirm button should now be enabled WITHOUT needing to test first
    await waitFor(() => {
      expect(screen.getByTestId("provider-draft-confirm")).not.toBeDisabled();
    });
  });

  it("does NOT render a per-draft Test button", async () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /btnAddModel/i }));
    pickFirstProvider();

    await waitFor(() => {
      expect(screen.queryByTestId("provider-draft-test")).toBeNull();
    });
  });
});
