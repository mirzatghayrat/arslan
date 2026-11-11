import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";

const request = vi.fn();
vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  request: (...args: unknown[]) => request(...args),
}));

import { ApiError } from "../api/client";
import type { ArslanServerMessage } from "../api/client.types";
import { toUiMessages } from "../api/adapters";
import { OPEN_SECTION_EVENT, takeSettingFocus } from "../lib/sections";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";
import SandboxCard from "./SandboxCard";
import { CERTIFICATES_SWITCH_ID } from "./settings/SandboxNetworkPanel";

const frame = (x: Partial<Extract<ArslanServerMessage, { type: "sandbox_card" }>>) =>
  useArslanStore.getState().handleFrame({ type: "sandbox_card", card_id: "c1", kind: "lan_device", ...x } as ArslanServerMessage);
const cards = () => useArslanStore.getState().items.flatMap((it) => (it.sandboxCard ? [it.sandboxCard] : []));

/** The chat's card for each sandbox item, as OrchestratorChat renders it (through toUiMessages). */
function Chat() {
  const items = useArslanStore((s) => s.items);
  return <>{toUiMessages(items).map((m) => (m.sandboxCard ? <SandboxCard key={m.id} card={m.sandboxCard} /> : null))}</>;
}

describe("SBX settings: the chat cards (the mock, in Chinese)", () => {
  beforeAll(async () => { await i18n.changeLanguage("zh"); });
  afterAll(async () => { await i18n.changeLanguage("en"); });
  beforeEach(() => {
    request.mockReset();
    useArslanStore.setState(initialArslanState(), true);
  });

  it("a card comes from its frame only: once per id, one certificate card open at a time", () => {
    frame({ card_id: "a", addresses: ["192.168.1.20"], host: "nas.local" });
    frame({ card_id: "a", addresses: ["192.168.1.20"], host: "nas.local" });     // replayed
    frame({ card_id: "b", addresses: [] });                                       // a device card with no device
    frame({ card_id: "c", kind: "certificates" });
    frame({ card_id: "d", kind: "certificates" });
    frame({ card_id: "e", kind: "something_new" as never });                     // a kind this window doesn't know
    expect(cards()).toEqual([
      { cardId: "a", kind: "lan_device", host: "nas.local", addresses: ["192.168.1.20"], state: "open" },
      { cardId: "c", kind: "certificates", state: "open" },
    ]);
  });

  it("the certificate card opens Settings at the switch, and turns nothing on itself", () => {
    frame({ card_id: "cert", kind: "certificates" });
    render(<Chat />);
    expect(screen.getByTestId("sandbox-card-title")).toHaveTextContent("证书检查没通过");
    expect(screen.getByText("这条命令联网时要用 macOS 的证书检查，沙盒里默认不让用。打开「允许沙盒里的命令检查系统证书」后再试一次。"))
      .toBeInTheDocument();
    const asked: unknown[] = [];
    const listen = (e: Event) => asked.push((e as CustomEvent).detail);
    window.addEventListener(OPEN_SECTION_EVENT, listen);
    fireEvent.click(screen.getByRole("button", { name: "去设置打开" }));
    window.removeEventListener(OPEN_SECTION_EVENT, listen);
    expect(asked).toEqual([{ section: "settings", sub: "abilities" }]);
    expect(takeSettingFocus(CERTIFICATES_SWITCH_ID)).toBe(true);
    expect(request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "不用" }));
    expect(screen.queryByTestId("sandbox-card")).toBeNull();
    expect(request).not.toHaveBeenCalled();
  });

  it("the device card shows the device as it will be pinned, and its click answers that card with that device", async () => {
    frame({ card_id: "card-7", host: "nas.local", addresses: ["192.168.1.20"] });
    render(<Chat />);
    expect(screen.getByTestId("sandbox-card-title")).toHaveTextContent("命令想连局域网里的设备 nas.local（192.168.1.20）");
    expect(screen.getByText("沙盒里的命令默认连不了局域网。信任这台设备后，它的所有端口都能连，随时能在设置里删掉。")).toBeInTheDocument();
    request.mockResolvedValueOnce({ devices: [{ host: "nas.local", address: "192.168.1.20" }] });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "信任这台设备" })); });
    expect(request).toHaveBeenCalledWith("/sandbox/cards/card-7",
      { method: "POST", body: JSON.stringify({ trust: true, host: "nas.local", addresses: ["192.168.1.20"] }) });
    expect(await screen.findByText("这台设备现在已经被信任，再试一次就能连。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "信任这台设备" })).toBeNull();
    expect(cards()[0].state).toBe("trusted");
  });

  it("a device reached by its IP is shown as that IP, and is answered with no name", async () => {
    frame({ card_id: "card-8", addresses: ["192.168.1.20"] });
    render(<Chat />);
    expect(screen.getByTestId("sandbox-card-title")).toHaveTextContent("命令想连局域网里的设备 192.168.1.20");
    request.mockResolvedValueOnce({ devices: [{ address: "192.168.1.20" }] });
    await act(async () => { fireEvent.click(screen.getByTestId("sandbox-card-trust")); });
    expect(request).toHaveBeenCalledWith("/sandbox/cards/card-8",
      { method: "POST", body: JSON.stringify({ trust: true, host: null, addresses: ["192.168.1.20"] }) });
  });

  it.each([404, 409])("a card the server no longer holds (%s) says so and keeps its button", async (status) => {
    frame({ card_id: "gone", addresses: ["192.168.1.20"] });
    render(<Chat />);
    request.mockRejectedValueOnce(new ApiError("x", status, { code: status === 404 ? "not_pending" : "not_shown" }));
    await act(async () => { fireEvent.click(screen.getByTestId("sandbox-card-trust")); });
    expect(await screen.findByRole("alert")).toHaveTextContent("这张卡已经失效了，可以在设置里加这台设备。");
    expect(screen.getByTestId("sandbox-card-trust")).toBeInTheDocument();
    expect(cards()[0].state).toBe("open");
  });

  it("「不用」 lets the device card go on the server too, and puts it away", async () => {
    frame({ card_id: "card-9", addresses: ["192.168.1.20"] });
    render(<Chat />);
    request.mockResolvedValueOnce({ devices: [] });
    fireEvent.click(screen.getByRole("button", { name: "不用" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/sandbox/cards/card-9",
      { method: "POST", body: JSON.stringify({ trust: false }) }));
    expect(screen.queryByTestId("sandbox-card")).toBeNull();
  });
});

describe("SBX settings: the chat cards in English", () => {
  beforeEach(() => useArslanStore.setState(initialArslanState(), true));

  it("names the switch as Settings does", async () => {
    await i18n.changeLanguage("en");
    frame({ card_id: "cert", kind: "certificates" });
    frame({ card_id: "lan", addresses: ["10.0.0.9"] });
    render(<Chat />);
    expect(screen.getByText(/Turn on “Allow system certificate checks in the sandbox”, then try again\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn it on in Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Trust this device" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Not now" })).toHaveLength(2);
  });
});
