/**
 * S6: "Remembered answers" is the last group of Settings › What Arslan may do, not an eighth nav entry. A deep link
 * (`openSection('settings', 'remembered')`) opens that page, scrolls the group to the top and highlights it briefly;
 * the Terminal group's pointer does the same. The two old lists it replaced are gone from the page.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { changeLanguage: vi.fn() } }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));
const request = vi.fn().mockResolvedValue([]);
vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
    embeddingStatus: vi.fn().mockResolvedValue(null),
    getAccessToken: vi.fn().mockResolvedValue({ token_required: false, token: null }),
  },
  API_BASE: "",
  request: (...args: unknown[]) => request(...args),
  listProviderConfigs: vi.fn().mockResolvedValue([]),
  setPrimaryProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  updateProviderConfig: vi.fn().mockResolvedValue({}),
}));
vi.mock("../stores/authStore", () => ({
  useAuthStore: Object.assign(
    (sel: (s: { token: string; setToken: (t: string) => void }) => unknown) => sel({ token: "", setToken: () => {} }),
    { getState: () => ({ token: "", setToken: () => {} }) },
  ),
}));

import SettingsScreen from "../components/SettingsScreen";
import { SECTION_ANCHORS, SETTINGS_SECTIONS, resolveSection } from "../components/settings/sectionRegistry";
import { readOpenSection } from "../lib/sections";
import type { AppSettings } from "../types";

const settings = { language: "en", orchestratorShellEnabled: true, shellConfirmPolicy: "ask_all" } as AppSettings;
const screenAt = (initialSection?: string) => render(<SettingsScreen settings={settings} setSettings={vi.fn()}
  llmProviders={[]} searchProviders={[]} backendStatus="online" initialSection={initialSection} />);

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe("the deep link to Remembered answers", () => {
  it("is a part of What Arslan may do, not a nav entry", () => {
    expect(resolveSection("remembered")).toBe("abilities");
    expect(SETTINGS_SECTIONS.map((s) => s.id)).not.toContain("remembered");
    expect(readOpenSection({ section: "settings", sub: "remembered" })).toEqual({ section: "settings", sub: "remembered" });
  });

  it("opens the page, scrolls the group to the top and highlights it for a moment", async () => {
    vi.useFakeTimers();
    const scrolled: Element[] = [];
    Element.prototype.scrollIntoView = vi.fn(function (this: Element) { scrolled.push(this); });
    screenAt("remembered");
    expect(screen.getByTestId("settings-abilities")).toBeInTheDocument();
    const group = screen.getByTestId("settings-remembered");
    expect(group.id).toBe(SECTION_ANCHORS.remembered.elementId);
    expect(scrolled).toEqual([group]);
    expect(group.dataset.highlighted).toBe("true");
    // Its lists load after the page opens (the page may have been too short): it scrolls there once more.
    await act(async () => {});
    expect(scrolled).toEqual([group, group]);
    act(() => { vi.advanceTimersByTime(1700); });
    expect(group.dataset.highlighted).toBeUndefined();
  });

  it("is the page's last group, and the Terminal group points at it", () => {
    vi.useFakeTimers();
    const scrolled: Element[] = [];
    Element.prototype.scrollIntoView = vi.fn(function (this: Element) { scrolled.push(this); });
    screenAt("abilities");
    const page = screen.getByTestId("settings-abilities");
    expect(page.lastElementChild).toBe(screen.getByTestId("settings-remembered"));
    expect(scrolled).toEqual([]);                                    // opening the page itself scrolls nowhere
    fireEvent.click(screen.getByTestId("settings-remembered-pointer"));
    expect(scrolled).toEqual([screen.getByTestId("settings-remembered")]);
    expect(screen.getByTestId("settings-remembered").dataset.highlighted).toBe("true");
  });

  it("the old lists are gone: only the new page asks for the rules and grants", async () => {
    screenAt("abilities");
    await act(async () => {});
    const paths = request.mock.calls.map(([path]) => path);
    expect(paths).toContain("/permissions/rules");
    expect(paths).toContain("/permissions/grants");
    expect(paths.some((p) => String(p).includes("terminal-rules") || String(p).includes("kind=outside"))).toBe(false);
    expect(screen.queryByTestId("terminal-rules")).toBeNull();
    expect(screen.queryByTestId("sandbox-grants")).toBeNull();
  });
});
