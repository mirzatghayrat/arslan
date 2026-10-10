/**
 * "Continue with OpenRouter" on the first-run film's model shot (0.1.60).
 *
 * The zero-card path: OAuth instead of pasting a key, a :free default model,
 * and money stays on OpenRouter's side. The URL travels backend → response →
 * the shell doorway — window.open is the mutation that must fail.
 */
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { language: "en", changeLanguage: vi.fn() },
  }),
}));
const start = vi.fn();
const status = vi.fn();
vi.mock("../api/client", () => ({
  addProviderConfig: vi.fn(),
  api: { updateSettings: vi.fn(async () => ({})) },
  getCatalog: vi.fn(async () => []),
  testLlm: vi.fn(),
  listProviderConfigs: vi.fn(async () => [
    { id: 1, label: "OpenRouter", provider: "openrouter", model: "deepseek/x:free" },
  ]),
  startOpenRouterOauth: (...a: unknown[]) => start(...a),
  getOpenRouterOauthStatus: (...a: unknown[]) => status(...a),
}));
const openExternal = vi.fn();
vi.mock("../lib/shell", () => ({
  openExternal: (...a: unknown[]) => openExternal(...a),
  shellAvailable: () => true,
}));
vi.mock("../components/settings/HandsSection", () => ({
  getHands: vi.fn(async () => ({ available: false })),
  askHandsPermission: vi.fn(),
  checkHands: vi.fn(),
}));
// Reduced motion: the film cuts instead of gliding, so a success moves on at once.
Object.defineProperty(window, "matchMedia", {
  configurable: true,
  value: (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }),
});

import FirstRunWizard from "../components/FirstRunWizard";

const props = {
  llmProviders: [{ key: "openai", label: "OpenAI", needs_key: true }],
  onAdded: vi.fn(),
  onClose: vi.fn(),
};

async function toKeyStep() {
  render(<FirstRunWizard {...(props as unknown as Parameters<typeof FirstRunWizard>[0])} />);
  // hello → model
  fireEvent.click(screen.getByTestId("first-run-next"));
  await waitFor(() => expect(screen.getByTestId("openrouter-signin")).toBeTruthy());
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("the OpenRouter button", () => {
  it("lives on the key step and routes the URL through the shell doorway", async () => {
    start.mockResolvedValue({ auth_url: "https://openrouter.ai/auth?x" });
    status.mockResolvedValue({ state: "done", config_id: 1, free_model: true, model: "deepseek/x:free" });
    await toKeyStep();
    fireEvent.click(screen.getByTestId("openrouter-signin"));
    await waitFor(() => expect(openExternal).toHaveBeenCalledWith("https://openrouter.ai/auth?x"));
    await waitFor(() => expect(props.onAdded).toHaveBeenCalled());
    // Success moves on to the folder choice — the wizard does NOT close yet.
    await waitFor(() => expect(screen.getByTestId("first-run-folders-wide")).toBeTruthy());
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("a refused authorization shows the error and keeps the wizard open", async () => {
    start.mockResolvedValue({ auth_url: "https://openrouter.ai/auth?x" });
    status.mockResolvedValue({ state: "error", error: "authorization refused: access_denied" });
    await toKeyStep();
    fireEvent.click(screen.getByTestId("openrouter-signin"));
    await waitFor(() => expect(screen.getByText(/access_denied/)).toBeTruthy());
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("a paid-fallback outcome is stated, not silent", async () => {
    // free_model=false means the flow could not find a :free model and used the
    // preset default — the user must see that their default may need credit.
    start.mockResolvedValue({ auth_url: "https://openrouter.ai/auth?x" });
    status.mockResolvedValue({ state: "done", config_id: 1, free_model: false, model: "anthropic/claude-sonnet-5" });
    await toKeyStep();
    fireEvent.click(screen.getByTestId("openrouter-signin"));
    await waitFor(() => expect(screen.getByText(/firstRun.openrouterPaidFallback/)).toBeTruthy());
    // Stated and then left to the user: no automatic move on past the notice.
    expect(screen.queryByTestId("first-run-folders-wide")).toBeNull();
    fireEvent.click(screen.getByTestId("first-run-continue"));
    expect(screen.getByTestId("first-run-folders-wide")).toBeTruthy();
  });
});
