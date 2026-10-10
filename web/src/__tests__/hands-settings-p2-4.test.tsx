// Hands v2 P2-4 (spec 2026-10-08-0157 §7.4): Screen Recording asked from Settings, the
// screenshot / borrow / away switches, apps allowed for good (by bundle id, running apps only)
// and apps never screenshotted; the six languages say what the switches do.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { language: "en" } }) }));
const request = vi.fn();
vi.mock("../api/client", () => ({ request: (...args: unknown[]) => request(...args) }));

import HandsSection from "../components/settings/HandsSection";
import { handsMessages } from "../locales/hands";
import { LANGS, stepText } from "../locales/island";

afterEach(() => { cleanup(); request.mockReset(); });

const state = (over: Record<string, unknown> = {}) => ({
  available: true, enabled: true, cursor: true, never: [], running: true, accessibility: true,
  screen_recording: false, screenshots: true, borrow: true, away: false,
  always: [{ bundle_id: "com.example.notes", name: "Notes", since: "2026-10-10" }], no_screenshots: ["Mail"],
  built_in: { never: [], look_only: [], click_only: [] }, ...over });

const calls = (method: string) => request.mock.calls.filter(([, init]) => (init?.method ?? "GET") === method);

describe("Hands settings (P2-4)", () => {
  it("asks macOS for Screen Recording only when it is known to be missing, with kind screen", async () => {
    request.mockImplementation(async (path: string) =>
      path === "/hands/permission" ? { screen_recording: true } : state());
    render(<HandsSection />);
    expect(await screen.findByTestId("hands-screen")).toHaveTextContent("hands.settings.screenNotGranted");
    fireEvent.click(screen.getByTestId("hands-ask-screen"));
    await waitFor(() => expect(screen.getByTestId("hands-screen")).toHaveTextContent("hands.settings.screenGranted"));
    const [, init] = calls("POST").find(([path]) => path === "/hands/permission")!;
    expect(JSON.parse(init.body)).toEqual({ kind: "screen" });
    expect(screen.queryByTestId("hands-ask-screen")).toBeNull();
    expect(screen.queryByTestId("hands-ask")).toBeNull();          // Accessibility is allowed: no prompt for it
  });

  it("each switch sends only its own setting", async () => {
    request.mockImplementation(async (_p: string, init?: RequestInit) =>
      init?.method === "PUT" ? state(JSON.parse(String(init.body))) : state());
    render(<HandsSection />);
    for (const [id, key, now] of [["hands-screenshots-toggle", "screenshots", true], ["hands-borrow-toggle", "borrow", true],
                                  ["hands-away-toggle", "away", false]] as const) {
      fireEvent.click(await screen.findByTestId(id));
      await waitFor(() => expect(JSON.parse(calls("PUT").at(-1)![1].body)).toEqual({ [key]: !now }));
    }
    expect(calls("PUT")).toHaveLength(3);
  });

  it("allows a running app for good by name, shows the error when it is not running, and removes by bundle id", async () => {
    request.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/hands/always") {
        const { app } = JSON.parse(String(init!.body));
        return app === "TextEdit"
          ? { ok: true, ...state({ always: [...state().always, { bundle_id: "com.apple.TextEdit", name: "TextEdit", since: "" }] }) }
          : { ok: false, code: "app_not_running" };
      }
      if (init?.method === "DELETE") return { ok: true, ...state({ always: [] }) };
      return state();
    });
    render(<HandsSection />);
    expect(await screen.findByTestId("hands-always")).toHaveTextContent("Notes");
    fireEvent.change(screen.getByTestId("hands-always-input"), { target: { value: "Pages" } });
    fireEvent.click(screen.getByTestId("hands-always-add"));
    expect(await screen.findByTestId("hands-always-error")).toHaveTextContent("hands.settings.alwaysNotRunning");
    expect(screen.getByTestId("hands-always-input")).toHaveValue("Pages");
    fireEvent.change(screen.getByTestId("hands-always-input"), { target: { value: "TextEdit" } });
    expect(screen.queryByTestId("hands-always-error")).toBeNull();
    fireEvent.click(screen.getByTestId("hands-always-add"));
    await waitFor(() => expect(screen.getByTestId("hands-always")).toHaveTextContent("TextEdit"));
    expect(screen.getByTestId("hands-always-input")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "hands.settings.remove Notes" }));
    await waitFor(() => expect(calls("DELETE").map(([p]) => p)).toEqual(["/hands/always/com.example.notes"]));
    await waitFor(() => expect(screen.getByTestId("hands-always")).not.toHaveTextContent("Notes"));
    expect(calls("PUT")).toEqual([]);
  });

  it("the never-screenshot list adds and removes through the settings", async () => {
    request.mockImplementation(async (_p: string, init?: RequestInit) =>
      init?.method === "PUT" ? state(JSON.parse(String(init.body))) : state());
    render(<HandsSection />);
    expect(await screen.findByTestId("hands-no-shots")).toHaveTextContent("Mail");
    fireEvent.change(screen.getByTestId("hands-no-shots-input"), { target: { value: "Messages" } });
    fireEvent.click(screen.getByTestId("hands-no-shots-add"));
    await waitFor(() => expect(JSON.parse(calls("PUT").at(-1)![1].body)).toEqual({ no_screenshots: ["Mail", "Messages"] }));
    fireEvent.click(screen.getByRole("button", { name: "hands.settings.remove Mail" }));
    await waitFor(() => expect(JSON.parse(calls("PUT").at(-1)![1].body)).toEqual({ no_screenshots: ["Messages"] }));
  });

  it("every new label has copy in all six languages, and no language still says it never screenshots", () => {
    const keys = ["screenshots", "screenshotsDesc", "borrow", "borrowDesc", "away", "awayDesc", "screen", "screenGranted",
                  "screenNotGranted", "always", "alwaysDesc", "alwaysPlaceholder", "alwaysNotRunning", "noShots", "noShotsDesc"];
    expect(Object.keys(handsMessages)).toHaveLength(6);
    for (const [lang, m] of Object.entries(handsMessages)) {
      const settings = m.settings as Record<string, string>;
      for (const k of keys) expect(settings[k], `${lang}.${k}`).toBeTruthy();
      expect(m.settings.lede, lang).not.toMatch(/never (takes )?screenshots|从不截图|不截屏/);
      expect(m.settings.cursorDesc, lang).not.toMatch(/never taken|不会占用|使いません|nunca se usan|nie benutzt|jamais utilisés/);
    }
  });

  it("the island says which apps one card asks for, in every language", () => {
    for (const lang of LANGS) {
      const text = stepText(lang, "desktop_access", "Notes · Pages");
      expect(text, lang).toContain("Notes · Pages");
      expect(text, lang).not.toContain("desktop access");
    }
  });
});
