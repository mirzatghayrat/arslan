/**
 * SBX-6a settings: the trusted local devices panel and the certificate switch.
 *
 * The panel adds a device only through the backend's resolve endpoint (which pins a name to the address it has
 * now) and shows the backend's refusal reason by code; the adapter round-trips the list through the stored JSON
 * string and drops malformed entries. Both controls show only while the terminal and its sandbox are on.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const requestMock = vi.fn();
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, request: (...args: unknown[]) => requestMock(...args) };
});

vi.mock("../components/BrowserPanel", () => ({ default: () => null }));
vi.mock("../components/settings/SandboxGrantsPanel", () => ({ default: () => null }));
vi.mock("../components/settings/TerminalRulesPanel", () => ({ default: () => null }));

import TrustedDevicesPanel from "../components/settings/TrustedDevicesPanel";
import AdvancedSection from "../components/settings/AdvancedSection";
import { ApiError } from "../api/client";
import { parseTrustedDevices, toUiSettings } from "../api/adapters";

describe("TrustedDevicesPanel", () => {
  beforeEach(() => requestMock.mockReset());

  it("adds the entry the backend resolved, pinned to its address", async () => {
    requestMock.mockResolvedValue({ host: "printer.local", address: "192.168.1.30" });
    const onChange = vi.fn();
    render(<TrustedDevicesPanel devices={[]} onChange={onChange} />);
    fireEvent.change(screen.getByTestId("trusted-device-input"), { target: { value: "  printer.local " } });
    fireEvent.click(screen.getByTestId("trusted-device-add"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith([{ host: "printer.local", address: "192.168.1.30" }]));
    expect(requestMock).toHaveBeenCalledWith("/settings/trusted-devices/resolve",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ host: "printer.local" }) }));
  });

  it("shows the refusal reason by code and adds nothing", async () => {
    requestMock.mockRejectedValueOnce(new ApiError("refused", 400, { code: "own_address" }));
    const onChange = vi.fn();
    render(<TrustedDevicesPanel devices={[]} onChange={onChange} />);
    fireEvent.change(screen.getByTestId("trusted-device-input"), { target: { value: "192.168.1.5" } });
    fireEvent.click(screen.getByTestId("trusted-device-add"));
    expect(await screen.findByTestId("trusted-device-error")).toHaveTextContent("settings.trustedDevicesRefused_own_address");
    expect(onChange).not.toHaveBeenCalled();
    expect(requestMock).toHaveBeenCalledTimes(1);
  });

  it("does not add the same device twice", async () => {
    requestMock.mockResolvedValue({ address: "192.168.1.30" });
    const onChange = vi.fn();
    render(<TrustedDevicesPanel devices={[{ address: "192.168.1.30" }]} onChange={onChange} />);
    fireEvent.change(screen.getByTestId("trusted-device-input"), { target: { value: "192.168.1.30" } });
    fireEvent.click(screen.getByTestId("trusted-device-add"));
    await waitFor(() => expect(requestMock).toHaveBeenCalled());
    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes only the device whose button was pressed", () => {
    const onChange = vi.fn();
    const devices = [{ host: "nas.local", address: "192.168.1.10" }, { address: "192.168.1.30" }];
    render(<TrustedDevicesPanel devices={devices} onChange={onChange} />);
    expect(screen.getByText("settings.trustedDevicesAddressOnly")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("trusted-device-remove-192.168.1.10"));
    expect(onChange).toHaveBeenCalledWith([{ address: "192.168.1.30" }]);
  });
});

describe("trusted devices adapter", () => {
  it("parses the stored list and drops malformed entries", () => {
    expect(parseTrustedDevices(undefined)).toEqual([]);
    expect(parseTrustedDevices("not json")).toEqual([]);
    expect(parseTrustedDevices('{"address":"192.168.1.30"}')).toEqual([]);
    expect(parseTrustedDevices('[{"host":"a.local","address":"192.168.1.2"},{"host":"b.local"},{"address":"192.168.1.3","host":7}]'))
      .toEqual([{ host: "a.local", address: "192.168.1.2" }, { address: "192.168.1.3" }]);
  });

  it("reads both new settings with their defaults off and empty", () => {
    const ui = toUiSettings({} as Parameters<typeof toUiSettings>[0]);
    expect(ui.sandboxSystemCertificates).toBe(false);
    expect(ui.sandboxTrustedDevices).toEqual([]);
  });
});

describe("AdvancedSection sandbox network controls", () => {
  type Props = React.ComponentProps<typeof AdvancedSection>;
  const base = (overrides: Partial<Props>): Props => ({
    telemetry: false, onTelemetryChange: vi.fn(),
    orchestratorShellEnabled: true, onOrchestratorShellChange: vi.fn(),
    workspaceDir: "", onWorkspaceDirChange: vi.fn(),
    lanDiscoveryEnabled: false, onLanDiscoveryChange: vi.fn(),
    sshEnabled: false, onSshChange: vi.fn(),
    defaultReadEnabled: true, onDefaultReadChange: vi.fn(),
    voiceInputLocale: "", onVoiceInputLocaleChange: vi.fn(),
    voiceMode: "push_to_talk", onVoiceModeChange: vi.fn(),
    voiceEndpointSilenceMs: 900, onVoiceEndpointSilenceChange: vi.fn(),
    shellConfirmPolicy: "ask_all", onShellConfirmPolicyChange: vi.fn(),
    onSandboxSystemCertificatesChange: vi.fn(), onSandboxTrustedDevicesChange: vi.fn(),
    ...overrides,
  });

  it("shows both controls while the terminal and its sandbox are on, and the switch saves", () => {
    const props = base({ terminalSandboxEnabled: true });
    render(<AdvancedSection {...props} />);
    expect(screen.getByTestId("trusted-devices")).toBeInTheDocument();
    const toggle = screen.getByTestId("settings-sandbox-certificates-toggle");
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    expect(props.onSandboxSystemCertificatesChange).toHaveBeenCalledWith(true);
  });

  it.each([
    ["the sandbox is off", { terminalSandboxEnabled: false }],
    ["the terminal is off", { orchestratorShellEnabled: false }],
  ])("hides both controls when %s", (_label, overrides) => {
    render(<AdvancedSection {...base(overrides as Partial<Props>)} />);
    expect(screen.queryByTestId("trusted-devices")).toBeNull();
    expect(screen.queryByTestId("settings-sandbox-certificates-toggle")).toBeNull();
  });
});
