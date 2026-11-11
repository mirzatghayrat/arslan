import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";

const request = vi.fn();
vi.mock("../../api/client", async (original) => ({
  ...(await original<typeof import("../../api/client")>()),
  request: (...args: unknown[]) => request(...args),
}));

import { ApiError } from "../../api/client";
import { OPEN_SECTION_EVENT, openSetting } from "../../lib/sections";
import SandboxNetworkPanel, { CERTIFICATES_SWITCH_ID } from "./SandboxNetworkPanel";

const NAS = { host: "nas.local", address: "192.168.1.20" };
const IP = { address: "192.168.1.42" };
const devices = (...list: object[]) => ({ devices: list });

describe("SBX settings: the certificate switch and the trusted local devices (the mock, in Chinese)", () => {
  beforeAll(async () => { await i18n.changeLanguage("zh"); });
  afterAll(async () => { await i18n.changeLanguage("en"); });
  beforeEach(() => request.mockReset());

  it("shows the switch off by default and saves it through the settings form", async () => {
    request.mockResolvedValueOnce(devices());
    const onChange = vi.fn();
    render(<SandboxNetworkPanel systemCertificates={false} onSystemCertificatesChange={onChange} />);
    const toggle = screen.getByRole("checkbox", { name: "允许沙盒里的命令检查系统证书" }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(screen.getByText(/打开后只在命令联网时允许，读不到你的钥匙串。默认关。/)).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
    expect(await screen.findByText("还没有信任的设备。")).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith("/settings/sandbox/trusted-devices");
  });

  it("lands on the switch when a card opened Settings for it", async () => {
    request.mockResolvedValueOnce(devices());
    const asked: unknown[] = [];
    const listen = (e: Event) => asked.push((e as CustomEvent).detail);
    window.addEventListener(OPEN_SECTION_EVENT, listen);
    openSetting("abilities", CERTIFICATES_SWITCH_ID);
    window.removeEventListener(OPEN_SECTION_EVENT, listen);
    expect(asked).toEqual([{ section: "settings", sub: "abilities" }]);
    render(<SandboxNetworkPanel systemCertificates={false} />);
    expect(document.activeElement).toBe(screen.getByTestId(CERTIFICATES_SWITCH_ID));
  });

  it("lists the devices, adds one by name or by IP, and stops trusting one", async () => {
    request.mockResolvedValueOnce(devices(NAS, IP));
    render(<SandboxNetworkPanel systemCertificates={false} />);
    const rows = await screen.findAllByTestId("trusted-device");
    expect(rows.map((r) => r.textContent)).toEqual(["nas.local192.168.1.20不再信任", "192.168.1.42不再信任"]);
    expect(screen.getByText("信任的本地设备")).toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "名称或局域网 IP" });
    expect(input).toHaveAttribute("placeholder", "名称或局域网 IP，比如 nas.local 或 192.168.1.20");

    request.mockResolvedValueOnce(devices(NAS, IP, { host: "printer.local", address: "192.168.1.30" }));
    fireEvent.change(input, { target: { value: " Printer.local " } });
    fireEvent.click(screen.getByRole("button", { name: "信任" }));
    await waitFor(() => expect(screen.getAllByTestId("trusted-device")).toHaveLength(3));
    expect(request).toHaveBeenLastCalledWith("/settings/sandbox/trusted-devices",
      { method: "POST", body: JSON.stringify({ device: "printer.local" }) });
    expect(input).toHaveValue("");

    request.mockResolvedValueOnce(devices(NAS, IP, { address: "10.0.0.9" }));
    fireEvent.change(input, { target: { value: "10.0.0.9" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(request).toHaveBeenLastCalledWith("/settings/sandbox/trusted-devices",
      { method: "POST", body: JSON.stringify({ device: "10.0.0.9" }) }));

    request.mockResolvedValueOnce(devices(IP));
    fireEvent.click(screen.getByTestId("trusted-device-remove-nas.local"));
    await waitFor(() => expect(screen.getAllByTestId("trusted-device")).toHaveLength(1));
    expect(request).toHaveBeenLastCalledWith("/settings/sandbox/trusted-devices?host=nas.local", { method: "DELETE" });
    request.mockResolvedValueOnce(devices());
    fireEvent.click(screen.getByTestId("trusted-device-remove-192.168.1.42"));
    expect(await screen.findByText("还没有信任的设备。")).toBeInTheDocument();
    expect(request).toHaveBeenLastCalledWith("/settings/sandbox/trusted-devices?address=192.168.1.42", { method: "DELETE" });
  });

  it.each([
    ["not_found", "gone.local", "找不到「gone.local」。用局域网里的名字（比如 nas.local）或 IP。"],
    ["not_lan", "8.8.8.8", "8.8.8.8 不是局域网地址。这里只能加局域网里的设备。"],
    ["own_address", "192.168.1.8", "这是这台 Mac 自己的地址，不能加。"],
    ["listed", "192.168.1.42", "已经在列表里了。"],
  ])("says what the server said when it refuses (%s) and adds nothing", async (code, value, words) => {
    request.mockResolvedValueOnce(devices(IP));
    render(<SandboxNetworkPanel systemCertificates={false} />);
    await screen.findAllByTestId("trusted-device");
    request.mockRejectedValueOnce(new ApiError(code, 422, { code, value }));
    fireEvent.change(screen.getByTestId("trusted-device-input"), { target: { value } });
    await act(async () => { fireEvent.click(screen.getByTestId("trusted-device-add")); });
    expect(await screen.findByRole("alert")).toHaveTextContent(words);
    expect(screen.getAllByTestId("trusted-device")).toHaveLength(1);
    expect(screen.getByTestId("trusted-device-input")).toHaveValue(value);
  });
});

describe("SBX settings in English", () => {
  beforeEach(() => request.mockReset());

  it("names the switch and the list as the model's note does", async () => {
    await i18n.changeLanguage("en");
    request.mockResolvedValueOnce(devices(NAS));
    render(<SandboxNetworkPanel systemCertificates />);
    expect((screen.getByRole("checkbox", { name: "Allow system certificate checks in the sandbox" }) as HTMLInputElement)
      .checked).toBe(true);
    expect(await screen.findByText("Trusted local devices")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop trusting" })).toBeInTheDocument();
  });
});
