/**
 * Proactivity settings: every control saves what it shows, a refused save puts the old value
 * back, and the one control that spends lives in Automation with its warning.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { ApiError } from "../api/client";
import type { ProactiveConfig, ProactiveWatch } from "../api/proactive";
import ProactiveSection from "../components/settings/ProactiveSection";
import ProactiveDiagnosisCap from "../components/settings/ProactiveDiagnosisCap";
import { FIELD_HOMES, SETTINGS_SECTIONS } from "../components/settings/sectionRegistry";

const api = vi.hoisted(() => ({
  config: vi.fn(), saveConfig: vi.fn(), watches: vi.fn(), addWatch: vi.fn(), updateWatch: vi.fn(), deleteWatch: vi.fn(),
  mutes: vi.fn(), unmute: vi.fn(),
}));
vi.mock("../api/proactive", async (original) => ({ ...(await original<typeof import("../api/proactive")>()), proactiveApi: api }));

const CONFIG: ProactiveConfig = { enabled: true, notify: true, notify_daily_cap: 5, quiet_start: "22:00", quiet_end: "08:00",
  job_followups: true, scheduled_problems: true, watches: true, brief_enabled: false, brief_time: "08:30", diagnosis_daily_usd: 0 };
const WATCH: ProactiveWatch = { id: 4, kind: "web", target: "https://example.com/pricing", label: "Pricing", enabled: true,
  interval_s: 21600, notify: true, last_error: null, last_checked_at: null, last_changed_at: null };

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.config.mockResolvedValue(CONFIG);
  api.saveConfig.mockImplementation(async (patch: Partial<ProactiveConfig>) => ({ ...CONFIG, ...patch }));
  api.watches.mockResolvedValue({ watches: [WATCH] });
  api.mutes.mockResolvedValue({ mutes: ["kind:web_change", "watch:4"] });
  void i18n.changeLanguage("en");
});
afterEach(cleanup);

const ready = async () => { render(<ProactiveSection />); await screen.findByTestId("proactive-watch-4"); };

describe("settings", () => {
  it("each switch saves exactly its own field", async () => {
    await ready();
    fireEvent.click(screen.getByTestId("proactive-toggle-enabled"));
    fireEvent.click(screen.getByTestId("proactive-toggle-notify"));
    fireEvent.click(screen.getByTestId("proactive-source-scheduled_problems"));
    fireEvent.click(screen.getByTestId("proactive-toggle-brief"));
    await waitFor(() => expect(api.saveConfig).toHaveBeenCalledTimes(4));
    expect(api.saveConfig.mock.calls.map(([patch]) => patch)).toEqual([
      { enabled: false }, { notify: false }, { scheduled_problems: false }, { brief_enabled: true }]);
  });

  it("quiet hours, cap and brief time save their values", async () => {
    api.config.mockResolvedValue({ ...CONFIG, brief_enabled: true });
    await ready();
    fireEvent.change(screen.getByTestId("proactive-quiet-start"), { target: { value: "23:15" } });
    fireEvent.change(screen.getByTestId("proactive-notify-cap"), { target: { value: "2" } });
    fireEvent.change(screen.getByTestId("proactive-brief-time"), { target: { value: "07:45" } });
    await waitFor(() => expect(api.saveConfig).toHaveBeenCalledTimes(3));
    expect(api.saveConfig.mock.calls.map(([patch]) => patch)).toEqual([{ quiet_start: "23:15" }, { notify_daily_cap: 2 }, { brief_time: "07:45" }]);
  });

  it("a refused save puts the switch back and says why", async () => {
    api.saveConfig.mockRejectedValue(new ApiError("invalid_config", 422));
    await ready();
    const toggle = screen.getByTestId("proactive-toggle-enabled") as HTMLInputElement;
    fireEvent.click(toggle);
    expect((await screen.findByRole("alert")).textContent).toBe("That value isn't allowed.");
    expect(toggle.checked).toBe(true);
  });

  it("turning the feature off disables choosing sources", async () => {
    api.config.mockResolvedValue({ ...CONFIG, enabled: false });
    await ready();
    // Disabled through the <fieldset>, which the element's own `.disabled` does not reflect.
    expect(screen.getByTestId("proactive-source-job_followups")).toBeDisabled();
  });

  it("the free section says nothing runs without the user, and points to where spending is set", async () => {
    await ready();
    expect(screen.getByText(/nothing runs until you choose Do it/)).toBeTruthy();
    expect(screen.getByText(/its daily limit sits under Automation/)).toBeTruthy();
    expect(screen.queryByTestId("proactive-diagnosis-limit")).toBeNull();
  });
});

describe("watches", () => {
  it("adds a page with the chosen interval and clears the form", async () => {
    api.addWatch.mockResolvedValue({ ...WATCH, id: 5 });
    await ready();
    const form = screen.getByTestId("proactive-add-watch");
    fireEvent.change(within(form).getByRole("textbox", { name: "Address or folder" }), { target: { value: "  https://example.org/news  " } });
    fireEvent.change(within(form).getByRole("combobox", { name: "Check every" }), { target: { value: "3600" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add watch" }));
    await waitFor(() => expect(api.addWatch).toHaveBeenCalledWith({ kind: "web", target: "https://example.org/news", interval_s: 3600, notify: true }));
    await waitFor(() => expect((within(form).getByRole("textbox", { name: "Address or folder" }) as HTMLInputElement).value).toBe(""));
  });

  it("a refused watch says why in words", async () => {
    api.addWatch.mockRejectedValue(new ApiError("outside_workspace", 422));
    await ready();
    const form = screen.getByTestId("proactive-add-watch");
    fireEvent.change(within(form).getByRole("combobox", { name: "Type" }), { target: { value: "folder" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "Address or folder" }), { target: { value: "/etc" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add watch" }));
    expect((await screen.findByRole("alert")).textContent).toBe("That folder isn't inside your workspace.");
    expect(api.addWatch.mock.calls[0][0].kind).toBe("folder");
  });

  it("pause, notify, interval and remove each call the API once", async () => {
    api.updateWatch.mockResolvedValue(WATCH);
    api.deleteWatch.mockResolvedValue({ ok: true });
    await ready();
    const row = screen.getByTestId("proactive-watch-4");
    fireEvent.click(within(row).getByRole("button", { name: "Pause" }));
    fireEvent.click(within(row).getByRole("checkbox", { name: "Notify me" }));
    fireEvent.change(within(row).getByRole("combobox", { name: "Check every" }), { target: { value: "86400" } });
    fireEvent.click(within(row).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.deleteWatch).toHaveBeenCalledWith(4));
    expect(api.updateWatch.mock.calls).toEqual([[4, { enabled: false }], [4, { notify: false }], [4, { interval_s: 86400 }]]);
  });

  it("warns when watches exist but checking them is switched off", async () => {
    api.config.mockResolvedValue({ ...CONFIG, watches: false });
    await ready();
    expect(screen.getByTestId("proactive-watches-off").textContent).toBe("Checking watches is switched off above, so none of these are being checked.");
  });

  it("warns too when the whole feature is off, and not when all is on", async () => {
    api.config.mockResolvedValue({ ...CONFIG, enabled: false });
    await ready();
    expect(screen.getByTestId("proactive-watches-off")).toBeTruthy();
    cleanup();
    api.config.mockResolvedValue(CONFIG);
    await ready();
    expect(screen.queryByTestId("proactive-watches-off")).toBeNull();
  });

  it("shows when a page could not be read", async () => {
    api.watches.mockResolvedValue({ watches: [{ ...WATCH, last_error: "HTTP 404" }] });
    await ready();
    expect(screen.getByText("Couldn't read it: HTTP 404")).toBeTruthy();
  });
});

describe("silenced", () => {
  it("names what is silenced in words and can lift it", async () => {
    api.unmute.mockResolvedValue({ ok: true });
    await ready();
    const box = screen.getByTestId("proactive-mutes");
    expect(within(box).getByText("All “Page changes”")).toBeTruthy();
    expect(within(box).getByText("Watch #4")).toBeTruthy();
    fireEvent.click(within(box).getAllByRole("button", { name: "Unsilence" })[0]);
    await waitFor(() => expect(api.unmute).toHaveBeenCalledWith("kind:web_change"));
  });
});

describe("the cause-guess limit", () => {
  it("lives in Automation, with the other spenders", () => {
    expect(FIELD_HOMES["proactive.diagnosis_cap"]).toBe("automation");
    const proactive = SETTINGS_SECTIONS.find((s) => s.id === "proactive");
    expect(proactive?.group).toBe("system");
  });

  it("is off by default, carries its honest warning, and saves the chosen limit", async () => {
    render(<ProactiveDiagnosisCap />);
    const select = await screen.findByTestId("proactive-diagnosis-limit") as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    expect(select.value).toBe("0");
    expect([...select.options].map((o) => o.text)).toEqual(["Off", "$0.25", "$0.50", "$1.00", "$2.00", "$5.00"]);
    expect(screen.getByTestId("proactive-diagnosis-spend-note").textContent).toMatch(/never for a model whose price Arslan does not know/);
    fireEvent.change(select, { target: { value: "0.5" } });
    await waitFor(() => expect(api.saveConfig).toHaveBeenCalledWith({ diagnosis_daily_usd: 0.5 }));
  });

  it("shows an unusual stored limit as itself instead of silently changing it", async () => {
    api.config.mockResolvedValue({ ...CONFIG, diagnosis_daily_usd: 0.3 });
    render(<ProactiveDiagnosisCap />);
    const select = await screen.findByTestId("proactive-diagnosis-limit") as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("0.3"));
  });

  it("a refused limit goes back to the old value", async () => {
    api.saveConfig.mockRejectedValue(new ApiError("invalid_config", 422));
    render(<ProactiveDiagnosisCap />);
    const select = await screen.findByTestId("proactive-diagnosis-limit") as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    fireEvent.change(select, { target: { value: "2" } });
    expect((await screen.findByRole("alert")).textContent).toBe("That value isn't allowed.");
    expect(select.value).toBe("0");
  });
});
