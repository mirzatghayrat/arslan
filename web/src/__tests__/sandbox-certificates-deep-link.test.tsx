/**
 * SBX settings: the certificate card's "Turn it on in Settings" (`openSection('settings', 'sandbox_certificates')`)
 * opens What Arslan may do with the certificate switch's row scrolled to the top, through S6's anchors.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

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
import { SECTION_ANCHORS } from "../components/settings/sectionRegistry";
import type { AppSettings } from "../types";

const settings = { language: "en", orchestratorShellEnabled: true, shellConfirmPolicy: "ask_all" } as AppSettings;

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the certificate card's deep link", () => {
  it("opens What Arslan may do at the certificate switch", () => {
    const scrolled: Element[] = [];
    Element.prototype.scrollIntoView = vi.fn(function (this: Element) { scrolled.push(this); });
    render(<SettingsScreen settings={settings} setSettings={vi.fn()} llmProviders={[]} searchProviders={[]}
      backendStatus="online" initialSection="sandbox_certificates" />);
    expect(screen.getByTestId("settings-abilities")).toBeInTheDocument();
    const row = document.getElementById(SECTION_ANCHORS.sandbox_certificates.elementId);
    expect(row).toContainElement(screen.getByTestId("settings-sandbox-certificates-toggle"));
    expect(scrolled).toEqual([row]);
  });
});
