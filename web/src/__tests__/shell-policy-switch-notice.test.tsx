/**
 * ASK1-a (v0.1.64; the user, 2026-11-07): "Ask only for risky commands" is the default again. Migration 0095 leaves
 * `shell_policy_switch_notice = "pending"` on an existing install whose stored policy isn't ask_risky; the window
 * shows the note, with the text for the policy as the server reads it, and writes "seen" at once, so it never shows
 * again. Nobody else ever sees it.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const { updateSettings } = vi.hoisted(() => ({ updateSettings: vi.fn() }));
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), api: { updateSettings } }));

import ShellPolicySwitchNotice from "../components/ShellPolicySwitchNotice";
import { useSettingsStore } from "../stores/settingsStore";
import type { AppSettings } from "../api/client.types";

function withFlag(flag: string | undefined, policy = "ask_all") {
  const settings = { shell_confirm_policy: policy } as AppSettings;
  if (flag !== undefined) settings.shell_policy_switch_notice = flag;
  act(() => useSettingsStore.getState().setSettings(settings));
}

describe("ShellPolicySwitchNotice", () => {
  beforeEach(() => {
    updateSettings.mockReset();
    updateSettings.mockResolvedValue({});
    useSettingsStore.setState({ settings: null });
  });

  it.each([
    ["ask_risky", "settings.policyNoticeRiskyTitle", "settings.policyNoticeRiskyBody"],   // was unset: moved
    ["ask_all", "settings.policyNoticeAllTitle", "settings.policyNoticeAllBody"],         // stored ask_all: kept
    ["", "settings.policyNoticeAllTitle", "settings.policyNoticeAllBody"],                // unknown: the strict text
  ])("the text follows the policy as read (%s)", (policy, title, body) => {
    withFlag("pending", policy);
    render(<ShellPolicySwitchNotice />);
    expect(screen.getByTestId("shell-policy-switch-notice").textContent).toContain(title);
    expect(screen.getByTestId("shell-policy-switch-notice-body").textContent).toBe(body);
  });

  it("a told user sees it once, with the way to switch, and it is marked seen at once", async () => {
    withFlag("pending");
    render(<ShellPolicySwitchNotice />);
    expect(screen.getByTestId("shell-policy-switch-notice-body").textContent).toBe("settings.policyNoticeAllBody");
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
