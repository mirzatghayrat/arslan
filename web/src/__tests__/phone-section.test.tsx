/** Settings › iPhone (mobile bridge §6.1): offline state, a pairing code, deciding a request
 *  only by clicking, removing a phone. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => (opts?.name ? `${key}:${opts.name}` : key) }),
}));

import PhoneSection from "../components/settings/PhoneSection";
import { api } from "../api/client";
import type { PhoneStatus } from "../api/client.types";
import { FIELD_HOMES, SETTINGS_SECTIONS } from "../components/settings/sectionRegistry";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const online = (over: Partial<PhoneStatus> = {}): PhoneStatus => ({
  connected: true, bridge: { device_id: "mac-1" }, devices: [], pending: [], code: null, ...over });

describe("Settings › iPhone", () => {
  it("tells everyone the iPhone app is coming, switch on or off, and the switch still works", async () => {
    vi.spyOn(api, "phoneStatus").mockResolvedValue({ connected: false, bridge: {}, devices: [], pending: [], code: null });
    const onChange = vi.fn();
    const { rerender } = render(<PhoneSection pollMs={60_000} enabled={false} onEnabledChange={onChange} />);
    expect(screen.getByTestId("phone-coming-soon")).toHaveTextContent("settings.phoneComingSoon");
    fireEvent.click(screen.getByTestId("settings-phone-enabled"));
    expect(onChange).toHaveBeenCalledWith(true);
    rerender(<PhoneSection pollMs={60_000} enabled onEnabledChange={onChange} />);
    expect(screen.getByTestId("phone-coming-soon")).toBeInTheDocument();
    await waitFor(() => expect(api.phoneStatus).toHaveBeenCalled());
  });

  it("says so when the Bridge is not running and offers no code", async () => {
    vi.spyOn(api, "phoneStatus").mockResolvedValue({ connected: false, bridge: {}, devices: [], pending: [], code: null });
    const onChange = vi.fn();
    const { rerender } = render(<PhoneSection pollMs={60_000} enabled={false} onEnabledChange={onChange} />);
    await waitFor(() => expect(api.phoneStatus).toHaveBeenCalled());
    expect(screen.queryByTestId("phone-offline")).toBeNull();          // off: nothing to wait for
    fireEvent.click(screen.getByTestId("settings-phone-enabled"));
    expect(onChange).toHaveBeenCalledWith(true);
    rerender(<PhoneSection pollMs={60_000} enabled onEnabledChange={onChange} />);
    expect(await screen.findByTestId("phone-offline")).toBeInTheDocument();
    expect(screen.queryByText("settings.phoneAdd")).toBeNull();
  });

  it("shows a one-time code as a QR", async () => {
    vi.spyOn(api, "phoneStatus").mockResolvedValue(online());
    const code = vi.spyOn(api, "phoneNewCode").mockResolvedValue({ uri: "arslan://pair?payload=x", qr_png: "iVBORw0KGgo=", expires_at: "t" });
    render(<PhoneSection pollMs={60_000} />);
    fireEvent.click(await screen.findByText("settings.phoneAdd"));
    await waitFor(() => expect(code).toHaveBeenCalledTimes(1));
    const img = (await screen.findByTestId("phone-code")).querySelector("img");
    expect(img?.getAttribute("src")).toBe("data:image/png;base64,iVBORw0KGgo=");
  });

  it("a request is decided only by a click here", async () => {
    vi.spyOn(api, "phoneStatus").mockResolvedValue(online({ pending: [{ request_id: "r1", phone_name: "Mirror iPhone" }] }));
    const decide = vi.spyOn(api, "phoneDecide").mockResolvedValue({ accepted: true });
    render(<PhoneSection pollMs={60_000} />);
    expect(await screen.findByTestId("phone-request-r1")).toHaveTextContent("settings.phoneRequest:Mirror iPhone");
    expect(decide).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("settings.phoneAccept"));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("r1", true));
    fireEvent.click(screen.getByText("settings.phoneDecline"));
    await waitFor(() => expect(decide).toHaveBeenLastCalledWith("r1", false));
  });

  it("lists paired phones and removes one", async () => {
    vi.spyOn(api, "phoneStatus").mockResolvedValue(online({ devices: [{ device_id: "iphone-1", name: "A", paired_at: "2026-10-03T00:00:00Z" }] }));
    const revoke = vi.spyOn(api, "phoneRevoke").mockResolvedValue({ revoked: true });
    render(<PhoneSection pollMs={60_000} />);
    expect(await screen.findByTestId("phone-device-iphone-1")).toHaveTextContent("A");
    fireEvent.click(screen.getByLabelText("settings.phoneRemove"));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("iphone-1"));
  });

  it("has a home in the settings registry", () => {
    expect(SETTINGS_SECTIONS.find((s) => s.id === "phone")?.group).toBe("system");
    expect(FIELD_HOMES["phone.devices"]).toBe("phone");
    expect(FIELD_HOMES["phone.enabled"]).toBe("phone");
  });
});
