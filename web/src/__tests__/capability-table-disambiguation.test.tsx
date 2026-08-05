/**
 * The provider capability table must not read as a verdict on whether tools work.
 *
 * Two different facts in Settings had collided on one word. The table's columns
 * are hand-authored 0-10 ratings from arslan/llm/catalog.py, used to pick a model
 * for a job; the tool-transport notice next to it states whether Arslan sends
 * tool definitions to the provider at all. A user could read "9" and "tools will
 * not run" on one screen and conclude the app contradicts itself.
 *
 * Locale strings resolve for real here rather than echoing keys back, because
 * the whole defect is what the words say. Against a key-echoing mock, reverting
 * the column to the ambiguous "Tools" passes — measured: that mutation stayed
 * green until this file existed.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "../locales/en.json";

function tr(key: string): string {
  const hit = key.split(".").reduce<unknown>(
    (node, part) =>
      node && typeof node === "object" ? (node as Record<string, unknown>)[part] : undefined,
    en as unknown,
  );
  if (typeof hit !== "string") return key;
  return hit;
}

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const raw = tr(key);
      return opts
        ? raw.replace(/\{\{(\w+)\}\}/g, (_, k) => String(opts[k] ?? ""))
        : raw;
    },
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

const mockGetCatalog = vi.fn();

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
  fetchProviderModels: vi
    .fn()
    .mockResolvedValue({ models: [], fetched_at: null, stale: false, error: null, source: "static" }),
  suggestPrimary: vi.fn().mockResolvedValue(null),
  getCatalog: (...a: unknown[]) => mockGetCatalog(...a),
  testLlm: vi.fn().mockResolvedValue({ ok: true }),
  testProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  probeProviderHealth: vi
    .fn()
    .mockResolvedValue({ state: "reachable_models", latency_ms: 1, detail: null, last_health_at: null }),
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: Object.assign(
    (sel: (s: { token: string; setToken: (t: string) => void }) => unknown) =>
      sel({ token: "", setToken: () => {} }),
    { getState: () => ({ token: "", setToken: () => {} }) },
  ),
}));

import ProviderConfigList from "../components/ProviderConfigList";
import type { ProviderConfig, ProviderOption } from "../api/client.types";

const providers: ProviderOption[] = [
  {
    key: "anthropic",
    label: "Anthropic",
    base_url: "",
    default_model: "claude",
    native: true,
    models: ["claude"],
  },
];
const configs: ProviderConfig[] = [
  {
    id: 1,
    label: "A",
    provider: "anthropic",
    model: "claude",
    base_url: "",
    api_key: "sk-x",
    key_status: "set",
    is_primary: true,
  },
];

beforeEach(() => {
  // A provider that scores HIGH on tool aptitude while Arslan cannot send it
  // tools at all — the exact pair that looked self-contradictory.
  mockGetCatalog.mockReset().mockResolvedValue([
    {
      provider: "anthropic",
      // Every score distinct, so asserting on one cell cannot accidentally
      // match another column's identical value.
      capabilities: { cost: 1, speed: 2, tool_calling: 9, reasoning: 4, long_context: 5 },
    },
  ]);
});

async function openTable() {
  render(
    <ProviderConfigList
      llmProviders={providers}
      providerConfigs={configs}
      onConfigsChange={vi.fn()}
    />,
  );
  const toggle = await screen.findByText(new RegExp(tr("settings.capabilityTable"), "i"));
  await userEvent.click(toggle);
}

describe("provider capability table", () => {
  it("explains that the ratings are for picking a model, not a tools-work verdict", async () => {
    await openTable();

    // The caption has to be ON SCREEN. Asserting the locale key merely exists
    // passes while the table renders without it — measured: removing the <p>
    // stayed green against the key-count guard alone.
    await waitFor(() =>
      expect(screen.getByText(new RegExp(tr("settings.capabilityTableNote").slice(0, 40)))).toBeTruthy(),
    );
  });

  it("names the column as an aptitude rating, not as bare 'Tools'", async () => {
    await openTable();

    const header = await screen.findByText(tr("settings.capColTools"));
    expect(header).toBeTruthy();
    // The other side: the bare word is what collided with the transport notice.
    expect(header.textContent?.trim().toLowerCase()).not.toBe("tools");
  });

  it("still shows the score, because the rating itself is useful", async () => {
    // Disambiguating must not turn into hiding. A user choosing a model for a
    // tool-heavy job needs this number.
    await openTable();
    await waitFor(() => expect(screen.getByText("9")).toBeTruthy());
  });

  it("says in the caption that it is not about Arslan sending tools", async () => {
    // The specific confusion, in words: the caption must draw the distinction,
    // not just add prose. A caption saying "these are scores" and nothing else
    // would leave the contradiction intact.
    const note = tr("settings.capabilityTableNote");
    expect(note).toMatch(/not/i);
    expect(note).toMatch(/Arslan/);
    expect(note).toMatch(/tool/i);
  });
});
