/**
 * A model card the person picked stays picked when the effect that picks the default runs late.
 *
 * ProviderConfigList keeps its selection valid in an effect that read `selectedId` from the render it closed over.
 * When Settings is open before the configs arrive (App loads them async), the first list renders with nothing
 * selected; a card clicked before that render's effects ran was put back to the primary when they did. Same race as
 * AskQueue's (askqueue-late-effect.test.tsx); here React's scheduler task is delayed on purpose, so the order is the
 * bad one every time.
 */
import { describe, it, expect, vi, afterEach } from "vitest";

vi.hoisted(() => {
  // React's scheduler runs passive effects on setImmediate in Node, captured when it loads: make it late.
  const g = globalThis as unknown as { setImmediate: (cb: (...a: unknown[]) => void, ...a: unknown[]) => unknown };
  g.setImmediate = (cb, ...a) => setTimeout(() => cb(...a), 80);
});

import { useEffect, useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { changeLanguage: vi.fn() } }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));
vi.mock("../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
    getAccessToken: vi.fn().mockResolvedValue({ token_required: false, token: null }),
  },
  API_BASE: "",
  addProviderConfig: vi.fn(),
  updateProviderConfig: vi.fn().mockResolvedValue({}),
  setPrimaryProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  deleteProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  fetchProviderModels: vi.fn().mockResolvedValue({ models: [], fetched_at: null, stale: false, error: null, source: "static" }),
  suggestPrimary: vi.fn().mockResolvedValue(null),
  getCatalog: vi.fn().mockResolvedValue([]),
  testLlm: vi.fn().mockResolvedValue({ ok: true }),
  testProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
}));
vi.mock("../stores/authStore", () => ({
  useAuthStore: Object.assign(
    (sel: (s: { token: string; setToken: (t: string) => void }) => unknown) => sel({ token: "", setToken: () => {} }),
    { getState: () => ({ token: "", setToken: () => {} }) },
  ),
}));

import ProviderConfigList from "../components/ProviderConfigList";
import type { ProviderConfig, ProviderOption } from "../api/client.types";

afterEach(cleanup);

const providers: ProviderOption[] = [
  { key: "deepseek", label: "DeepSeek", base_url: "", default_model: "deepseek-chat", native: false, models: ["deepseek-chat"] },
  { key: "qwen", label: "Qwen", base_url: "", default_model: "qwen-max", native: false, models: ["qwen-max"] },
];
const configs: ProviderConfig[] = [
  { id: 1, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "de...cd", is_primary: true },
  { id: 2, label: "B", provider: "qwen", model: "qwen-max", base_url: "", api_key: "qw...ef", is_primary: false },
];

/**
 * Settings open at launch: App loads the configs on its own, so they arrive after the list has rendered once with
 * its own catalog, outside act.
 */
function Late() {
  const [cfgs, setCfgs] = useState<ProviderConfig[]>([]);
  useEffect(() => { const timer = setTimeout(() => setCfgs(configs), 400); return () => clearTimeout(timer); }, []);
  return <ProviderConfigList llmProviders={providers} providerConfigs={cfgs} onConfigsChange={setCfgs} />;
}

describe("ProviderConfigList", () => {
  it("keeps the card picked when the effect that picks the primary runs late", async () => {
    render(<Late />);
    fireEvent.click(await screen.findByTestId("provider-card-row-1", {}, { timeout: 2000 }));
    await act(async () => { await new Promise((r) => setTimeout(r, 400)); });   // the late effect has run by now
    expect(screen.getByTestId("provider-card-row-1")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("provider-card-row-0")).toHaveAttribute("data-selected", "false");
  });
});
