/**
 * FirstRunWizard — the four-step flow (language → how it works → connect →
 * hello), the test-before-save key path, the save-anyway escape, the hello
 * step's name → profileStore wiring, and the firstRunShouldShow gate.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

const mockAddProviderConfig = vi.fn();
const mockUpdateSettings = vi.fn();
const mockTestLlm = vi.fn();
const mockGetCatalog = vi.fn();

vi.mock("../api/client", () => ({
  api: {
    updateSettings: (...a: unknown[]) => mockUpdateSettings(...a),
  },
  addProviderConfig: (...a: unknown[]) => mockAddProviderConfig(...a),
  testLlm: (...a: unknown[]) => mockTestLlm(...a),
  getCatalog: (...a: unknown[]) => mockGetCatalog(...a),
  listProviderConfigs: vi.fn(async () => []),
  startOpenRouterOauth: vi.fn(),
  getOpenRouterOauthStatus: vi.fn(),
}));
vi.mock("../lib/shell", () => ({
  openExternal: vi.fn(),
  shellAvailable: () => true,
}));

import FirstRunWizard from "../components/FirstRunWizard";
import { firstRunShouldShow, getFirstRunSeen } from "../lib/firstRun";
import { useProfileStore } from "../stores/profileStore";
import type { ProviderOption } from "../api/client.types";

const providers: ProviderOption[] = [
  {
    key: "deepseek",
    label: "DeepSeek",
    base_url: "",
    default_model: "deepseek-chat",
    native: false,
    models: ["deepseek-chat"],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useProfileStore.setState({ displayName: "" });
  mockUpdateSettings.mockResolvedValue({});
  mockGetCatalog.mockResolvedValue([
    {
      provider: "deepseek",
      capabilities: { cost: 5, speed: 4, tool_calling: 4, reasoning: 4, long_context: 3 },
      languages: {},
    },
  ]);
  mockAddProviderConfig.mockResolvedValue({
    id: 7,
    label: "DeepSeek",
    provider: "deepseek",
    model: "deepseek-chat",
    base_url: "",
    api_key: "",
    is_primary: true,
  });
});

/** language → how it works → connect. */
function toKeyStep() {
  fireEvent.click(screen.getByTestId("first-run-next")); // → how it works
  fireEvent.click(screen.getByTestId("first-run-next")); // → connect
}

describe("firstRunShouldShow gate", () => {
  it("shows only when ready, no provider, and not seen", () => {
    expect(firstRunShouldShow({ ready: true, hasProvider: false, seen: false })).toBe(true);
    // A provider already configured → does NOT show.
    expect(firstRunShouldShow({ ready: true, hasProvider: true, seen: false })).toBe(false);
    // Not yet loaded → does NOT show (avoids flash).
    expect(firstRunShouldShow({ ready: false, hasProvider: false, seen: false })).toBe(false);
    // Already seen → does NOT show.
    expect(firstRunShouldShow({ ready: true, hasProvider: false, seen: true })).toBe(false);
  });
});

describe("FirstRunWizard", () => {
  it("starts on the language step and walks language → tour → connect → hello", async () => {
    render(<FirstRunWizard llmProviders={providers} onAdded={vi.fn()} onClose={vi.fn()} />);

    // Step 1: language FIRST — so every later step renders in the chosen language.
    expect(screen.getByText("firstRun.stepLanguage")).toBeInTheDocument();
    expect(screen.getByTestId("first-run-lang-fr")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("first-run-next"));
    expect(screen.getByText("firstRun.howTitle")).toBeInTheDocument();
    expect(screen.getByText("firstRun.how4Body")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("first-run-next"));
    expect(screen.getByText("firstRun.stepKey")).toBeInTheDocument();
    expect(screen.getByTestId("first-run-key")).toBeInTheDocument();

    // "Add later" skips the key but still lands on hello, not out of the wizard.
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    expect(screen.getByTestId("first-run-name")).toBeInTheDocument();
  });

  it("shows the provider capability caption from the server catalog", async () => {
    render(<FirstRunWizard llmProviders={providers} onAdded={vi.fn()} onClose={vi.fn()} />);
    toKeyStep();
    await waitFor(() => expect(screen.getByTestId("first-run-capabilities")).toBeInTheDocument());
    expect(mockGetCatalog).toHaveBeenCalled();
  });

  it("dismissing (X) sets the seen flag and calls onClose", () => {
    const onClose = vi.fn();
    render(<FirstRunWizard llmProviders={providers} onAdded={vi.fn()} onClose={onClose} />);

    expect(getFirstRunSeen()).toBe(false);
    fireEvent.click(screen.getByTestId("first-run-dismiss"));
    expect(getFirstRunSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("a key that passes the test is saved and advances to hello", async () => {
    const onAdded = vi.fn();
    const user = userEvent.setup();
    mockTestLlm.mockResolvedValue({ ok: true, latency_ms: 240 });
    render(<FirstRunWizard llmProviders={providers} onAdded={onAdded} onClose={vi.fn()} />);
    toKeyStep();

    await user.type(screen.getByTestId("first-run-key"), "sk-real-key");
    fireEvent.click(screen.getByTestId("first-run-test-save"));

    await waitFor(() => {
      expect(mockTestLlm).toHaveBeenCalledWith({
        provider: "deepseek",
        model: "deepseek-chat",
        base_url: "",
        api_key: "sk-real-key",
      });
    });
    await waitFor(() => expect(mockAddProviderConfig).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));
    // Advanced to hello — the wizard is NOT closed yet.
    expect(screen.getByTestId("first-run-name")).toBeInTheDocument();
  });

  it("a failing key shows the real error, does NOT save, and offers save-anyway", async () => {
    const onAdded = vi.fn();
    const user = userEvent.setup();
    mockTestLlm.mockResolvedValue({ ok: false, error: "401 invalid api key" });
    render(<FirstRunWizard llmProviders={providers} onAdded={onAdded} onClose={vi.fn()} />);
    toKeyStep();

    await user.type(screen.getByTestId("first-run-key"), "sk-bad-key");
    fireEvent.click(screen.getByTestId("first-run-test-save"));

    await waitFor(() => expect(screen.getByText(/401 invalid api key/)).toBeInTheDocument());
    expect(mockAddProviderConfig).not.toHaveBeenCalled();

    // The stated escape: save anyway → saved blind, advances to hello.
    fireEvent.click(screen.getByTestId("first-run-save-anyway"));
    await waitFor(() => expect(mockAddProviderConfig).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("first-run-name")).toBeInTheDocument();
  });

  it("finishing hello with a name stores it in the profileStore", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<FirstRunWizard llmProviders={providers} onAdded={vi.fn()} onClose={onClose} />);
    toKeyStep();
    fireEvent.click(screen.getByTestId("first-run-add-later"));

    await user.type(screen.getByTestId("first-run-name"), "  Mirzat  ");
    fireEvent.click(screen.getByTestId("first-run-finish"));

    expect(useProfileStore.getState().displayName).toBe("Mirzat");
    expect(getFirstRunSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("finishing hello without a name leaves the profile untouched", () => {
    const onClose = vi.fn();
    render(<FirstRunWizard llmProviders={providers} onAdded={vi.fn()} onClose={onClose} />);
    toKeyStep();
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    fireEvent.click(screen.getByTestId("first-run-finish"));

    expect(useProfileStore.getState().displayName).toBe("");
    expect(mockAddProviderConfig).not.toHaveBeenCalled();
    expect(getFirstRunSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
