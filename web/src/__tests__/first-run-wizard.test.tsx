/**
 * FirstRunWizard — the first-run film (0.1.60, docs/specs/2026-10-11-0160-first-run.md):
 * hello → model → folders → (Hands, when here and not allowed) → you, the explicit folder choice,
 * the live Hands check, the folded own-key path (tested before save, save-anyway kept), the name,
 * the hand-off of the head into the app, and the firstRunShouldShow gate.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
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

vi.mock("../api/client", () => ({
  api: {
    updateSettings: (...a: unknown[]) => mockUpdateSettings(...a),
  },
  addProviderConfig: (...a: unknown[]) => mockAddProviderConfig(...a),
  testLlm: (...a: unknown[]) => mockTestLlm(...a),
  listProviderConfigs: vi.fn(async () => []),
  startOpenRouterOauth: vi.fn(),
  getOpenRouterOauthStatus: vi.fn(),
}));
vi.mock("../lib/shell", () => ({
  openExternal: vi.fn(),
  shellAvailable: () => true,
}));
const mockGetHands = vi.fn();
const mockAskHands = vi.fn();
const mockCheckHands = vi.fn();
vi.mock("../components/settings/HandsSection", () => ({
  getHands: (...a: unknown[]) => mockGetHands(...a),
  askHandsPermission: (...a: unknown[]) => mockAskHands(...a),
  checkHands: (...a: unknown[]) => mockCheckHands(...a),
}));

import FirstRunWizard, { HANDOFF_MS } from "../components/FirstRunWizard";
import { firstRunShouldShow, getFirstRunSeen, readFirstTasks } from "../lib/firstRun";
import { useProfileStore } from "../stores/profileStore";
import type { ProviderOption } from "../api/client.types";

const providers: ProviderOption[] = [
  { key: "deepseek", label: "DeepSeek", base_url: "", default_model: "deepseek-chat", native: false, models: ["deepseek-chat"] },
];

/** Reduced motion makes the film cut instead of glide, so the walk runs without waiting on the camera. */
function motion(reduced: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (q: string) => ({ matches: reduced && q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }),
  });
}

const shot = () => screen.getByTestId("first-run").getAttribute("data-shot");
const wizard = (over: Partial<Parameters<typeof FirstRunWizard>[0]> = {}) =>
  render(<FirstRunWizard llmProviders={providers} onAdded={vi.fn()} onClose={vi.fn()} {...over} />);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  motion(true);
  useProfileStore.setState({ displayName: "" });
  mockUpdateSettings.mockResolvedValue({});
  mockGetHands.mockResolvedValue({ available: false });
  mockAddProviderConfig.mockResolvedValue({
    id: 7, label: "DeepSeek", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "", is_primary: true,
  });
});
afterEach(() => {
  vi.useRealTimers();
});

describe("firstRunShouldShow gate", () => {
  it("shows only when ready, no provider, and not seen", () => {
    expect(firstRunShouldShow({ ready: true, hasProvider: false, seen: false })).toBe(true);
    expect(firstRunShouldShow({ ready: true, hasProvider: true, seen: false })).toBe(false);
    expect(firstRunShouldShow({ ready: false, hasProvider: false, seen: false })).toBe(false);
    expect(firstRunShouldShow({ ready: true, hasProvider: false, seen: true })).toBe(false);
  });
});

describe("FirstRunWizard", () => {
  it.each(["en", "zh", "ja", "es", "de", "fr"])("switches to %s at once and keeps the host in step", (code) => {
    mockUpdateSettings.mockReturnValue(new Promise(() => {}));
    const onLanguageChange = vi.fn();
    const onClose = vi.fn();
    wizard({ onLanguageChange, onClose });
    fireEvent.click(screen.getByTestId(`first-run-lang-${code}`));
    expect(onLanguageChange).toHaveBeenCalledWith(code);
    expect(mockUpdateSettings).toHaveBeenCalledWith({ language: code });
    expect(screen.getByTestId(`first-run-lang-${code}`)).toHaveAttribute("aria-pressed", "true");
    expect(shot()).toBe("hello");                           // language is not a step of its own
    fireEvent.click(screen.getByTestId("first-run-dismiss"));
    expect(onLanguageChange).toHaveBeenCalledBefore(onClose);
  });

  it("walks hello → model → folders → you, with no tour and no capability score", async () => {
    wizard();
    expect(shot()).toBe("hello");
    expect(screen.getByText("firstRun.helloTitle")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("first-run-next"));
    expect(shot()).toBe("model");
    expect(screen.queryByText("firstRun.howTitle")).toBeNull();
    expect(screen.queryByTestId("first-run-capabilities")).toBeNull();
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    expect(shot()).toBe("folders");
    fireEvent.click(screen.getByTestId("first-run-folders-own"));
    await waitFor(() => expect(shot()).toBe("you"));       // Hands is not here: no Hands shot
    expect(screen.getByTestId("first-run-name")).toBeInTheDocument();
  });

  it("the folder choice is explicit: nothing preselected, no way past without one, each writes its value", async () => {
    wizard();
    fireEvent.click(screen.getByTestId("first-run-next"));
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    expect(shot()).toBe("folders");
    expect(screen.getByTestId("first-run-folders-wide")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("first-run-folders-own")).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTestId("first-run-next")).toBeNull();
    expect(screen.queryByTestId("first-run-add-later")).toBeNull();
    fireEvent.click(screen.getByTestId("first-run-folders-wide"));
    expect(mockUpdateSettings).toHaveBeenCalledWith({ default_read_enabled: "true" });
    await waitFor(() => expect(shot()).toBe("you"));
  });

  it("choosing only its own folder turns default reading off", async () => {
    wizard();
    fireEvent.click(screen.getByTestId("first-run-next"));
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    fireEvent.click(screen.getByTestId("first-run-folders-own"));
    expect(mockUpdateSettings).toHaveBeenCalledWith({ default_read_enabled: "false" });
    expect(mockUpdateSettings).not.toHaveBeenCalledWith({ default_read_enabled: "true" });
  });

  it("Hands: asks for macOS's prompt, finds the switch with a live check, and moves on by itself", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockGetHands.mockResolvedValue({ available: true, accessibility: false });
    mockAskHands.mockResolvedValue({ accessibility: false });
    mockCheckHands.mockResolvedValueOnce({ running: true, accessibility: false })
      .mockResolvedValue({ running: true, accessibility: true });
    wizard();
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByTestId("first-run-next"));
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    fireEvent.click(screen.getByTestId("first-run-folders-wide"));
    await waitFor(() => expect(shot()).toBe("hands"));
    expect(screen.getByTestId("first-run-hands-status")).toHaveTextContent("firstRun.handsIdle");
    fireEvent.click(screen.getByTestId("first-run-hands-open"));
    await waitFor(() => expect(mockAskHands).toHaveBeenCalledWith("accessibility"));
    expect(screen.getByTestId("first-run-hands-status")).toHaveTextContent("firstRun.handsWaiting");
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(shot()).toBe("hands");                            // the first check: not yet
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    await waitFor(() => expect(shot()).toBe("you"));
    expect(mockCheckHands).toHaveBeenCalledTimes(2);
  });

  it("Hands: Not now skips; already allowed means no Hands shot at all", async () => {
    mockGetHands.mockResolvedValue({ available: true, accessibility: false });
    const first = wizard();
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByTestId("first-run-next"));
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    fireEvent.click(screen.getByTestId("first-run-folders-own"));
    await waitFor(() => expect(shot()).toBe("hands"));
    fireEvent.click(screen.getByTestId("first-run-hands-skip"));
    expect(shot()).toBe("you");
    expect(mockAskHands).not.toHaveBeenCalled();
    first.unmount();

    mockGetHands.mockResolvedValue({ available: true, accessibility: true });
    wizard();
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByTestId("first-run-next"));
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    fireEvent.click(screen.getByTestId("first-run-folders-own"));
    await waitFor(() => expect(shot()).toBe("you"));
  });

  it("your own key stays folded until asked; a key that passes is saved and the film moves on", async () => {
    const onAdded = vi.fn();
    const user = userEvent.setup();
    mockTestLlm.mockResolvedValue({ ok: true, latency_ms: 240 });
    wizard({ onAdded });
    fireEvent.click(screen.getByTestId("first-run-next"));
    expect(screen.queryByTestId("first-run-key")).toBeNull();
    fireEvent.click(screen.getByTestId("first-run-own-key"));
    await user.type(screen.getByTestId("first-run-key"), "sk-real-key");
    fireEvent.click(screen.getByTestId("first-run-test-save"));
    await waitFor(() => expect(mockTestLlm).toHaveBeenCalledWith({
      provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "sk-real-key",
    }));
    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(shot()).toBe("folders"));
  });

  it("a failing key shows the real error, does NOT save, and offers save-anyway", async () => {
    const onAdded = vi.fn();
    const user = userEvent.setup();
    mockTestLlm.mockResolvedValue({ ok: false, error: "401 invalid api key" });
    wizard({ onAdded });
    fireEvent.click(screen.getByTestId("first-run-next"));
    fireEvent.click(screen.getByTestId("first-run-own-key"));
    await user.type(screen.getByTestId("first-run-key"), "sk-bad-key");
    fireEvent.click(screen.getByTestId("first-run-test-save"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("401 invalid api key"));
    expect(mockAddProviderConfig).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("first-run-save-anyway"));
    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(shot()).toBe("folders"));
  });

  it("Start saves the name, records what was turned on, and (reduced motion) closes at once", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    wizard({ onClose });
    fireEvent.click(screen.getByTestId("first-run-next"));
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    fireEvent.click(screen.getByTestId("first-run-folders-wide"));
    await waitFor(() => expect(shot()).toBe("you"));
    await user.type(screen.getByTestId("first-run-name"), "  Ada  ");
    fireEvent.click(screen.getByTestId("first-run-finish"));
    expect(useProfileStore.getState().displayName).toBe("Ada");
    expect(readFirstTasks()).toEqual({ folders: true, hands: false });
    expect(getFirstRunSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("with motion, the head travels to its place in the app before the wizard closes", async () => {
    motion(false);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const anchor = document.createElement("img");
    anchor.setAttribute("data-brand-anchor", "");
    anchor.getBoundingClientRect = () => ({ left: 600, top: 300, width: 44, height: 44, right: 644, bottom: 344, x: 600, y: 300, toJSON() {} });
    document.body.appendChild(anchor);
    const onClose = vi.fn();
    wizard({ onClose });
    fireEvent.click(screen.getByTestId("first-run-next"));
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    fireEvent.click(screen.getByTestId("first-run-folders-own"));
    await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
    expect(shot()).toBe("you");
    fireEvent.click(screen.getByTestId("first-run-finish"));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByTestId("first-run")).toHaveClass("fr2-leaving");
    const head = screen.getByTestId("first-run-head");
    const size = parseFloat(head.style.width);
    // Centred on the anchor (622, 322) and shrunk to its 44 px.
    expect(head.style.transform).toBe(`translate(${622 - size / 2}px, ${322 - size / 2}px) scale(${44 / size})`);
    await act(async () => { await vi.advanceTimersByTimeAsync(HANDOFF_MS + 50); });
    expect(onClose).toHaveBeenCalledTimes(1);
    anchor.remove();
  });

  it("the head follows the theme: ink on a light stage, paper on a dark one", () => {
    const light = wizard();
    expect(document.querySelector(".mascot")).toHaveClass("ink");
    light.unmount();
    document.documentElement.classList.add("dark");
    wizard();
    expect(document.querySelector(".mascot")).not.toHaveClass("ink");
  });

  it("the mouth carries the moment: asking on folders, a smile once chosen", async () => {
    motion(false);
    wizard();
    fireEvent.click(screen.getByTestId("first-run-next"));
    fireEvent.click(screen.getByTestId("first-run-add-later"));
    expect(screen.getByTestId("first-run-head")).toHaveAttribute("data-mood", "approval");
    fireEvent.click(screen.getByTestId("first-run-folders-wide"));
    expect(screen.getByTestId("first-run-head")).toHaveAttribute("data-mood", "finished");
  });

  it("dismissing (×) sets the seen flag and calls onClose", () => {
    const onClose = vi.fn();
    wizard({ onClose });
    expect(getFirstRunSeen()).toBe(false);
    fireEvent.click(screen.getByTestId("first-run-dismiss"));
    expect(getFirstRunSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("is a labelled dialog, and Esc does not skip setup (0.1.55 S5)", () => {
    const onClose = vi.fn();
    wizard({ onClose });
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const title = document.getElementById(dialog.getAttribute("aria-labelledby")!);
    expect(title?.tagName).toBe("H1");
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(getFirstRunSeen()).toBe(false);
  });
});
