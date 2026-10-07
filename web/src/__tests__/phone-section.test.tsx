/** Settings › iPhone (mobile bridge §6.1): offline state, a pairing code, deciding a request
 *  only by clicking, removing a phone. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) =>
    (opts?.name ? `${key}:${opts.name}` : opts?.when ? `${key}:${opts.when}` : opts?.n !== undefined ? `${key}:${opts.n}` : key) }),
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

  // §3.3 (2026-10-07): a phone is "connecting" until the Bridge has heard from it.
  it("shows each phone as Connecting… or Connected with when it was last seen", async () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60_000 - 1000).toISOString();
    vi.spyOn(api, "phoneStatus").mockResolvedValue(online({ devices: [
      { device_id: "iphone-1", name: "A", paired_at: "2026-10-07T00:00:00Z", state: "connecting" },
      { device_id: "iphone-2", name: "B", paired_at: "2026-10-07T00:00:00Z", state: "connected", last_seen: fiveMinutesAgo },
      { device_id: "iphone-3", name: "C", paired_at: "2026-10-07T00:00:00Z" },
    ] }));
    render(<PhoneSection pollMs={60_000} />);
    const connecting = await screen.findByTestId("phone-device-state-iphone-1");
    expect(connecting).toHaveTextContent("settings.phoneConnecting");
    expect(connecting.querySelector(".animate-pulse")).not.toBeNull();
    const connected = screen.getByTestId("phone-device-state-iphone-2");
    expect(connected).toHaveTextContent("settings.phoneConnectedSeen:settings.timeMinutesAgo:5");
    expect(connected.querySelector(".animate-pulse")).toBeNull();
    expect(screen.getByTestId("phone-device-iphone-2")).toHaveTextContent("settings.phonePairedAt");
    expect(screen.queryByTestId("phone-device-state-iphone-3")).toBeNull();   // an older Bridge says nothing
  });

  it("a phone just allowed shows as Connecting… at once, then as the Bridge lists it", async () => {
    const request = { request_id: "r1", phone_id: "iphone-new", phone_name: "Mirror iPhone" };
    const status = vi.spyOn(api, "phoneStatus").mockResolvedValue(online({ pending: [request] }));
    vi.spyOn(api, "phoneDecide").mockImplementation(async () => {
      status.mockResolvedValue(online());                       // the Bridge's new list is not in yet
      return { accepted: true };
    });
    render(<PhoneSection pollMs={100} />);
    fireEvent.click(await screen.findByText("settings.phoneAccept"));
    const row = await screen.findByTestId("phone-device-iphone-new");
    expect(row).toHaveTextContent("Mirror iPhone");
    expect(screen.getByTestId("phone-device-state-iphone-new")).toHaveTextContent("settings.phoneConnecting");
    expect(screen.queryByText("settings.phoneNone")).toBeNull();
    // The Bridge's list names it and says it has heard from it: one row, its own state.
    status.mockResolvedValue(online({ devices: [{ device_id: "iphone-new", name: "Mirror iPhone",
      paired_at: new Date().toISOString(), state: "connected", last_seen: new Date().toISOString() }] }));
    await waitFor(() => expect(screen.getByTestId("phone-device-state-iphone-new")).toHaveAttribute("data-state", "connected"));
    expect(screen.getAllByTestId("phone-device-iphone-new")).toHaveLength(1);
    expect(screen.getByTestId("phone-device-state-iphone-new")).toHaveTextContent("settings.phoneConnectedSeen:settings.timeJustNow");
  });

  it("an allowed phone the Bridge never lists stops showing as Connecting… after a while", async () => {
    const request = { request_id: "r1", phone_id: "iphone-new", phone_name: "Mirror iPhone" };
    const status = vi.spyOn(api, "phoneStatus").mockResolvedValue(online({ pending: [request] }));
    // Each poll is a fresh object, as from the network (the same object would not re-render).
    vi.spyOn(api, "phoneDecide").mockImplementation(async () => { status.mockImplementation(async () => online()); return { accepted: true }; });
    render(<PhoneSection pollMs={100} />);
    fireEvent.click(await screen.findByText("settings.phoneAccept"));
    await screen.findByTestId("phone-device-iphone-new");
    const later = Date.now() + 16_000;
    vi.spyOn(Date, "now").mockReturnValue(later);                 // e.g. the Mac refused it (the code had expired)
    await waitFor(() => expect(screen.queryByTestId("phone-device-iphone-new")).toBeNull());
    expect(screen.getByText("settings.phoneNone")).toBeInTheDocument();
  });

  it("has a home in the settings registry", () => {
    expect(SETTINGS_SECTIONS.find((s) => s.id === "phone")?.group).toBe("system");
    expect(FIELD_HOMES["phone.devices"]).toBe("phone");
    expect(FIELD_HOMES["phone.enabled"]).toBe("phone");
  });
});
