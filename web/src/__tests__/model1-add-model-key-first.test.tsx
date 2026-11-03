/**
 * MODEL1 (v0.1.64): Add model asks for the API key first, then offers the provider's live model list, fetched
 * once with that key before anything is saved; when the provider can't be reached it shows Arslan's built-in list,
 * marked as such, with the reason and a way to try again (card docs/plans/0164/MODEL1-add-model-key-first.md).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key),
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: null }) },
}));

const preview = vi.fn();
const add = vi.fn();
vi.mock("../api/client", () => ({
  api: { updateSettings: vi.fn().mockResolvedValue({}) },
  API_BASE: "",
  previewProviderModels: (...a: unknown[]) => preview(...a),
  addProviderConfig: (...a: unknown[]) => add(...a),
  updateProviderConfig: vi.fn(),
  setPrimaryProviderConfig: vi.fn(),
  deleteProviderConfig: vi.fn(),
  testLlm: vi.fn(),
  testProviderConfig: vi.fn(),
  fetchProviderModels: vi.fn().mockResolvedValue({ models: [], fetched_at: null, stale: false, error: null, source: "api" }),
  probeProviderHealth: vi.fn().mockResolvedValue({ state: "reachable_models", latency_ms: 1, detail: null, last_health_at: null }),
}));

import ProviderConfigList from "../components/ProviderConfigList";
import type { ProviderOption } from "../api/client.types";

const providers: ProviderOption[] = [
  { key: "anthropic", label: "Anthropic Claude", base_url: "", default_model: "claude-sonnet-5-5", native: true,
    models: ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] },
];
const KEY = "sk-ant-model1-typed";
const live = (ids: string[]) => ({
  models: ids.map((id) => ({ id, display_name: null, context_window: null, capabilities: [], source: "api" })),
  fetched_at: "2026-11-03T00:00:00", stale: false, error: null, source: "api",
});

function openDraft() {
  render(<ProviderConfigList llmProviders={providers} providerConfigs={[]} onConfigsChange={vi.fn()} />);
  fireEvent.click(screen.getByTestId("provider-add-model"));
}
const keyInput = () => screen.getByTestId("provider-draft-key") as HTMLInputElement;
async function optionTexts() {
  fireEvent.focus(screen.getByTestId("provider-draft-model"));     // the combobox opens on focus
  return (await screen.findAllByRole("option")).map((o) => o.textContent ?? "");
}

beforeEach(() => {
  vi.clearAllMocks();
  preview.mockResolvedValue(live(["claude-opus-5-5", "claude-sonnet-5-5"]));
});

describe("the key comes before the model", () => {
  it("lays the form out as provider, key, then model", () => {
    openDraft();
    const provider = screen.getByText("settings.providerLabel");
    const model = screen.getByTestId("provider-draft-model");
    expect(provider.compareDocumentPosition(keyInput()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(keyInput().compareDocumentPosition(model) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByTestId("provider-draft-key-hint")).toBeTruthy();
  });

  it("asks for nothing until a key is typed", async () => {
    openDraft();
    await new Promise((r) => setTimeout(r, 800));
    expect(preview).not.toHaveBeenCalled();
  });
});

describe("a typed key fetches the live list once", () => {
  it("sends provider, base URL and key once, then offers the live models, marked live", async () => {
    openDraft();
    fireEvent.change(keyInput(), { target: { value: "sk-ant" } });
    fireEvent.change(keyInput(), { target: { value: KEY } });
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(preview).toHaveBeenCalledWith({ provider: "anthropic", base_url: "", api_key: KEY });
    expect((await screen.findByTestId("provider-draft-model-source")).dataset.source).toBe("live");
    const texts = await optionTexts();
    expect(texts).toEqual(expect.arrayContaining([
      expect.stringContaining("claude-opus-5-5"), expect.stringContaining("claude-sonnet-5-5")]));
    expect(texts.some((t) => t.includes("claude-haiku-5-5"))).toBe(false);     // the built-in list is not shown
  });
});

describe("a failed fetch shows the built-in list, marked", () => {
  it("says it couldn't reach the provider, gives the reason, and tries again on request", async () => {
    preview.mockResolvedValueOnce({ ...live(["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]),
      source: "static", stale: true, error: "The provider refused this API key." });
    openDraft();
    fireEvent.change(keyInput(), { target: { value: KEY } });
    const notice = await screen.findByTestId("provider-draft-fallback", undefined, { timeout: 2000 });
    expect(notice.textContent).toContain("settings.addModelFallback");
    expect(notice.textContent).toContain("The provider refused this API key.");
    expect(screen.getByTestId("provider-draft-model-source").dataset.source).toBe("built-in");
    fireEvent.click(screen.getByTestId("provider-draft-retry"));
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByTestId("provider-draft-fallback")).toBeNull());
  });
});

describe("only the latest key's answer counts", () => {
  it("drops a late answer for a key that has since been changed", async () => {
    let landOld!: (v: unknown) => void;
    preview.mockImplementationOnce(() => new Promise((r) => { landOld = r; }))
      .mockResolvedValueOnce(live(["claude-sonnet-5-5"]));
    openDraft();
    fireEvent.change(keyInput(), { target: { value: "sk-ant-old-key" } });
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(1), { timeout: 2000 });
    fireEvent.change(keyInput(), { target: { value: KEY } });
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2), { timeout: 2000 });
    await screen.findByText(/settings\.addModelLive.*"count":1/);
    await act(async () => { landOld(live(["claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1"])); });
    expect(screen.getByTestId("provider-draft-model-source").textContent).toContain('"count":1');
  });
});

describe("nothing is kept", () => {
  it("Cancel stores nothing, and an answer that arrives afterwards changes nothing", async () => {
    let land!: (v: unknown) => void;
    preview.mockImplementationOnce(() => new Promise((r) => { land = r; }));
    openDraft();
    fireEvent.change(keyInput(), { target: { value: KEY } });
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(1), { timeout: 2000 });
    fireEvent.click(screen.getByText("common.cancel"));
    await act(async () => { land(live(["claude-opus-5-5"])); });
    expect(add).not.toHaveBeenCalled();
    expect(screen.queryByTestId("provider-draft-key")).toBeNull();
  });
});
