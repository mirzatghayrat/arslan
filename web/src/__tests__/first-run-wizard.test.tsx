/**
 * FirstRunWizard — steps render, completing/dismissing sets the seen flag, and
 * the gate (firstRunShouldShow) hides it once a provider is configured.
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

vi.mock("../api/client", () => ({
  api: {
    updateSettings: (...a: unknown[]) => mockUpdateSettings(...a),
  },
  addProviderConfig: (...a: unknown[]) => mockAddProviderConfig(...a),
}));

import FirstRunWizard from "../components/FirstRunWizard";
import { firstRunShouldShow, getFirstRunSeen } from "../lib/firstRun";
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
  mockUpdateSettings.mockResolvedValue({});
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
  it("walks through welcome → language → connect steps", async () => {
    render(<FirstRunWizard llmProviders={providers} onAdded={vi.fn()} onClose={vi.fn()} />);

    // Step 0: welcome
    expect(screen.getByText("firstRun.title")).toBeInTheDocument();

    // → language
    fireEvent.click(screen.getByTestId("first-run-next"));
    expect(screen.getByText("firstRun.stepLanguage")).toBeInTheDocument();
    expect(screen.getByTestId("first-run-lang-fr")).toBeInTheDocument();

    // → connect a model
    fireEvent.click(screen.getByTestId("first-run-next"));
    expect(screen.getByText("firstRun.stepKey")).toBeInTheDocument();
    expect(screen.getByTestId("first-run-key")).toBeInTheDocument();
  });

  it("dismissing (X) sets the seen flag and calls onClose", () => {
    const onClose = vi.fn();
    render(<FirstRunWizard llmProviders={providers} onAdded={vi.fn()} onClose={onClose} />);

    expect(getFirstRunSeen()).toBe(false);
    fireEvent.click(screen.getByTestId("first-run-dismiss"));
    expect(getFirstRunSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("'Add later' (no key) finishes without creating a config", async () => {
    const onClose = vi.fn();
    const onAdded = vi.fn();
    render(<FirstRunWizard llmProviders={providers} onAdded={onAdded} onClose={onClose} />);

    fireEvent.click(screen.getByTestId("first-run-next")); // → language
    fireEvent.click(screen.getByTestId("first-run-next")); // → connect
    fireEvent.click(screen.getByTestId("first-run-add-later"));

    expect(mockAddProviderConfig).not.toHaveBeenCalled();
    expect(onAdded).not.toHaveBeenCalled();
    expect(getFirstRunSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Finish with a key saves via addProviderConfig and reports it up", async () => {
    const onClose = vi.fn();
    const onAdded = vi.fn();
    const user = userEvent.setup();
    render(<FirstRunWizard llmProviders={providers} onAdded={onAdded} onClose={onClose} />);

    fireEvent.click(screen.getByTestId("first-run-next")); // → language
    fireEvent.click(screen.getByTestId("first-run-next")); // → connect

    await user.type(screen.getByTestId("first-run-key"), "sk-real-key");
    fireEvent.click(screen.getByTestId("first-run-finish"));

    await waitFor(() => {
      expect(mockAddProviderConfig).toHaveBeenCalledWith({
        label: "DeepSeek",
        provider: "deepseek",
        model: "deepseek-chat",
        base_url: "",
        api_key: "sk-real-key",
      });
    });
    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));
    expect(getFirstRunSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
