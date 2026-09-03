/**
 * AdvancedSection — the "Advanced" settings section.
 *
 * Verifies the section is self-contained and hosts (per spec B1): the telemetry
 * toggle, the orchestrator-shell toggle, the confirm-policy Select (shown only
 * when shell is enabled), and the spawn-mode Select. Also asserts the spawn-mode
 * desc + option labels now use the NEW i18n keys (the hardcoded English is gone)
 * and that the toggle / Select onChange callbacks fire. Behavior mirrors the
 * pre-extraction inline controls — no persistence change here (Task 6 owns save).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import AdvancedSection from "../components/settings/AdvancedSection";

type Props = React.ComponentProps<typeof AdvancedSection>;

function setup(overrides: Partial<Props> = {}) {
  const props: Props = {
    telemetry: false,
    onTelemetryChange: vi.fn(),
    orchestratorShellEnabled: false,
    onOrchestratorShellChange: vi.fn(),
    workspaceDir: "",
    onWorkspaceDirChange: vi.fn(),
    lanDiscoveryEnabled: false,
    onLanDiscoveryChange: vi.fn(),
    sshEnabled: false,
    onSshChange: vi.fn(),
    defaultReadEnabled: true, onDefaultReadChange: vi.fn(),
    voiceOutputEnabled: false, onVoiceOutputChange: vi.fn(),
    voiceInputLocale: "", onVoiceInputLocaleChange: vi.fn(),
    voiceMode: "push_to_talk", onVoiceModeChange: vi.fn(),
    voiceEndpointSilenceMs: 900, onVoiceEndpointSilenceChange: vi.fn(),
    shellConfirmPolicy: "ask_all",
    onShellConfirmPolicyChange: vi.fn(),
    spawnMode: "auto",
    onSpawnModeChange: vi.fn(),
    ...overrides,
  };
  render(<AdvancedSection {...props} />);
  return props;
}

describe("AdvancedSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the telemetry toggle, shell toggle, and spawn-mode Select", () => {
    setup();
    expect(document.getElementById("settings-telemetry-toggle")).not.toBeNull();
    expect(document.getElementById("settings-shell-toggle")).not.toBeNull();
    expect(document.getElementById("settings-spawn-mode")).not.toBeNull();
  });

  it("shows the confirm-policy Select only when the shell is enabled", () => {
    setup({ orchestratorShellEnabled: false });
    expect(document.getElementById("settings-shell-policy")).toBeNull();
    // Re-render with shell enabled.
    setup({ orchestratorShellEnabled: true });
    expect(document.getElementById("settings-shell-policy")).not.toBeNull();
  });

  it("fires onTelemetryChange when the telemetry toggle is flipped", () => {
    const props = setup({ telemetry: false });
    fireEvent.click(document.getElementById("settings-telemetry-toggle") as HTMLInputElement);
    expect(props.onTelemetryChange).toHaveBeenCalledWith(true);
  });

  it("fires onOrchestratorShellChange when the shell toggle is flipped", () => {
    const props = setup({ orchestratorShellEnabled: false });
    fireEvent.click(document.getElementById("settings-shell-toggle") as HTMLInputElement);
    expect(props.onOrchestratorShellChange).toHaveBeenCalledWith(true);
  });

  it("fires onShellConfirmPolicyChange when a policy option is picked", async () => {
    const user = userEvent.setup();
    const props = setup({ orchestratorShellEnabled: true });
    await user.click(document.getElementById("settings-shell-policy") as HTMLButtonElement);
    const risky = screen
      .getAllByRole("option")
      .find((o) => /shellPolicyAskRisky/.test(o.textContent ?? ""));
    expect(risky).toBeTruthy();
    await user.click(risky as HTMLElement);
    expect(props.onShellConfirmPolicyChange).toHaveBeenCalledWith("ask_risky");
  });

  it("spawn-mode uses the NEW i18n keys (no hardcoded English)", () => {
    setup({ spawnMode: "auto" });
    // The desc + the selected-option label render via i18n keys.
    expect(screen.getByText("settings.spawnModeDesc")).toBeInTheDocument();
    expect(screen.getByText("settings.spawnModeAuto")).toBeInTheDocument();
    // The old hardcoded English literals must be gone.
    expect(screen.queryByText("Autonomous Synthesis")).toBeNull();
    expect(screen.queryByText(/Choose how sub-agents are created/)).toBeNull();
  });

  it("fires onSpawnModeChange when a mode option is picked", async () => {
    const user = userEvent.setup();
    const props = setup({ spawnMode: "auto" });
    await user.click(document.getElementById("settings-spawn-mode") as HTMLButtonElement);
    const interactive = screen
      .getAllByRole("option")
      .find((o) => /spawnModeInteractive/.test(o.textContent ?? ""));
    expect(interactive).toBeTruthy();
    await user.click(interactive as HTMLElement);
    expect(props.onSpawnModeChange).toHaveBeenCalledWith("interactive");
  });

  it("offers the three voice modes and reports the pick", () => {
    const props = setup({ voiceMode: "push_to_talk" });
    const sel = screen.getByTestId("voice-mode") as HTMLSelectElement;
    expect(Array.from(sel.options).map((o) => o.value)).toEqual(["off", "push_to_talk", "conversation"]);
    fireEvent.change(sel, { target: { value: "conversation" } });
    expect(props.onVoiceModeChange).toHaveBeenCalledWith("conversation");
  });

  it("the endpoint silence is a number in milliseconds, clamped to 300–3000", () => {
    const props = setup({ voiceEndpointSilenceMs: 900 });
    const input = screen.getByTestId("voice-endpoint-silence") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "50" } });
    expect(props.onVoiceEndpointSilenceChange).toHaveBeenLastCalledWith(300);
    fireEvent.change(input, { target: { value: "1500" } });
    expect(props.onVoiceEndpointSilenceChange).toHaveBeenLastCalledWith(1500);
  });
});
