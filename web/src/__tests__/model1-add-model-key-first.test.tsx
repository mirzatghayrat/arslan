/**
 * MODEL1 (v0.1.64): Add model asks for the API key first, then offers the provider's live model list, fetched
 * once with that key before anything is saved; when the provider can't be reached it shows Arslan's built-in list,
 * marked as such, with the reason and a way to try again (card docs/plans/0164/MODEL1-add-model-key-first.md).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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

import ProviderConfigList, { PREVIEW_DEBOUNCE_MS } from "../components/ProviderConfigList";
import type { ProviderOption } from "../api/client.types";

const providers: ProviderOption[] = [
  { key: "anthropic", label: "Anthropic Claude", base_url: "", default_model: "claude-sonnet-5-5", native: true,
    models: ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] },
  { key: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com", default_model: "deepseek-v4-flash", native: false,
    models: ["deepseek-v4-pro", "deepseek-v4-flash"] },
  { key: "custom", label: "OpenAI-compatible (custom)", base_url: "", default_model: "", native: false, models: [] },
];
const KEY = "sk-ant-model1-typed";
const live = (ids: string[]) => ({
  models: ids.map((id) => ({ id, display_name: null, context_window: null, capabilities: [], source: "api" })),
  fetched_at: "2026-11-03T00:00:00", stale: false, error: null, source: "api",
});

function openEmptyDraft() {
  render(<ProviderConfigList llmProviders={providers} providerConfigs={[]} onConfigsChange={vi.fn()} />);
  fireEvent.click(screen.getByTestId("provider-add-model"));
}
function pick(label: string) {
  fireEvent.click(screen.getByLabelText("Provider"));
  fireEvent.pointerDown(screen.getByRole("option", { name: new RegExp(label) }));
}
function openDraft(label = "Anthropic Claude") {
  openEmptyDraft();
  pick(label);
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

describe("a key goes only to the provider the user picked (max review, finding 1)", () => {
  it("starts with no provider, and the key can't be typed until one is picked", () => {
    openEmptyDraft();
    expect(screen.getByLabelText("Provider").textContent).toContain("settings.addModelChooseProvider");
    expect(keyInput().disabled).toBe(true);
    pick("DeepSeek");
    expect(keyInput().disabled).toBe(false);
  });

  it("clears the key when the provider changes, so nothing goes to the new one", async () => {
    openDraft("DeepSeek");
    fireEvent.change(keyInput(), { target: { value: KEY } });
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(1), { timeout: 2000 });
    pick("Anthropic Claude");
    expect(keyInput().value).toBe("");
    await new Promise((r) => setTimeout(r, 800));
    expect(preview).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("provider-draft-model-source").dataset.source).toBe("built-in");
  });
});

describe("a base URL is used once it is finished (max review, finding 2)", () => {
  const url = () => screen.getByTestId("provider-draft-baseurl") as HTMLInputElement;

  it("sends nothing to a host still being typed, and fetches once when the field is left", async () => {
    openDraft("OpenAI-compatible");
    fireEvent.change(keyInput(), { target: { value: KEY } });
    await new Promise((r) => setTimeout(r, 700));
    expect(preview).not.toHaveBeenCalled();                  // no address yet: nowhere to send it
    fireEvent.change(url(), { target: { value: "http://192.168" } });
    await new Promise((r) => setTimeout(r, 700));
    fireEvent.change(url(), { target: { value: "http://192.168.1.20:1234/v1" } });
    await new Promise((r) => setTimeout(r, 700));
    expect(preview).not.toHaveBeenCalled();
    fireEvent.blur(url());
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(preview).toHaveBeenCalledWith({ provider: "custom", base_url: "http://192.168.1.20:1234/v1", api_key: KEY });
  });

  it("a preset's address counts as finished until it is edited", async () => {
    openDraft("DeepSeek");
    fireEvent.change(keyInput(), { target: { value: KEY } });
    await waitFor(() => expect(preview).toHaveBeenCalledWith(
      { provider: "deepseek", base_url: "https://api.deepseek.com", api_key: KEY }), { timeout: 2000 });
  });
});

describe("the wait while typing (max review, finding 6)", () => {
  afterEach(() => vi.useRealTimers());

  it("does not use a key until typing has paused", async () => {
    openDraft();
    vi.useFakeTimers();
    fireEvent.change(keyInput(), { target: { value: KEY } });
    await act(async () => { vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS - 1); });
    expect(preview).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(preview).toHaveBeenCalledTimes(1);
    expect(PREVIEW_DEBOUNCE_MS).toBeGreaterThanOrEqual(300);
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
    for (const store of [window.localStorage, window.sessionStorage]) {   // max review, finding 6
      for (let i = 0; i < store.length; i += 1) expect(store.getItem(store.key(i)!) ?? "").not.toContain(KEY);
    }
    expect(window.location.href).not.toContain(KEY);
  });
});
