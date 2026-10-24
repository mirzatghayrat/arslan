/**
 * R63 (the user's decision, 10-24): someone migration 0070 moved off "Ask only for risky commands" is told once,
 * after the upgrade. The server leaves `shell_policy_switch_notice = "pending"`; the window shows the notice and
 * writes "seen" at once, so it never shows again. Nobody else ever sees it.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const { updateSettings } = vi.hoisted(() => ({ updateSettings: vi.fn() }));
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), api: { updateSettings } }));

import ShellPolicySwitchNotice from "../components/ShellPolicySwitchNotice";
import { useSettingsStore } from "../stores/settingsStore";
import type { AppSettings } from "../api/client.types";

function withFlag(flag: string | undefined) {
  const settings = { shell_confirm_policy: "ask_all" } as AppSettings;
  if (flag !== undefined) settings.shell_policy_switch_notice = flag;
  act(() => useSettingsStore.getState().setSettings(settings));
}

describe("ShellPolicySwitchNotice", () => {
  beforeEach(() => {
    updateSettings.mockReset();
    updateSettings.mockResolvedValue({});
    useSettingsStore.setState({ settings: null });
  });

  it("a switched user sees it once, with the reason and the way back, and it is marked seen at once", async () => {
    withFlag("pending");
    render(<ShellPolicySwitchNotice />);
    expect(screen.getByTestId("shell-policy-switch-notice-body").textContent).toBe("settings.policyNoticeBody");
    expect(updateSettings).toHaveBeenCalledTimes(1);
    expect(updateSettings).toHaveBeenCalledWith({ shell_policy_switch_notice: "seen" });
    await waitFor(() => expect(useSettingsStore.getState().settings?.shell_policy_switch_notice).toBe("seen"));
    fireEvent.click(screen.getByTestId("shell-policy-switch-notice-ok"));
    expect(screen.queryByTestId("shell-policy-switch-notice")).toBeNull();
  });

  it.each([["seen"], [""], [undefined]])("nobody else sees it (flag %s)", (flag) => {
    withFlag(flag);
    render(<ShellPolicySwitchNotice />);
    expect(screen.queryByTestId("shell-policy-switch-notice")).toBeNull();
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it("before settings load it shows nothing, then shows when they arrive pending", () => {
    render(<ShellPolicySwitchNotice />);
    expect(screen.queryByTestId("shell-policy-switch-notice")).toBeNull();
    withFlag("pending");
    expect(screen.getByTestId("shell-policy-switch-notice")).toBeTruthy();
  });

  it("a stale settings reload that says pending again after it was marked seen does not show it twice", async () => {
    withFlag("pending");
    render(<ShellPolicySwitchNotice />);
    await waitFor(() => expect(useSettingsStore.getState().settings?.shell_policy_switch_notice).toBe("seen"));
    fireEvent.click(screen.getByTestId("shell-policy-switch-notice-ok"));
    withFlag("pending");
    expect(screen.queryByTestId("shell-policy-switch-notice")).toBeNull();
    expect(updateSettings).toHaveBeenCalledTimes(1);
  });

  it("a failed write keeps the window quiet; it may show once more next start", async () => {
    updateSettings.mockRejectedValue(new Error("offline"));
    withFlag("pending");
    render(<ShellPolicySwitchNotice />);
    await waitFor(() => expect(updateSettings).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("shell-policy-switch-notice-ok"));
    expect(screen.queryByTestId("shell-policy-switch-notice")).toBeNull();
  });
});
