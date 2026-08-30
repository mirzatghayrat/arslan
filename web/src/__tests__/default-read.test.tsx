/**
 * The default-read toggle and its first-run consent line (spec 2026-08-24).
 *
 * macOS shows NO permission dialog for Desktop/Documents/Downloads to this app
 * class (measured), so without the first-run line the default would be silent.
 * These pin that the switch is default-ON and its description names the folders
 * — the two things a copy-only regression would quietly drop.
 */
import { render, screen } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import AdvancedSection from "../components/settings/AdvancedSection";
import { toUiSettings } from "../api/adapters";
import "../i18n";

type Props = React.ComponentProps<typeof AdvancedSection>;
function props(over: Partial<Props> = {}): Props {
  return {
    telemetry: false, onTelemetryChange: vi.fn(),
    orchestratorShellEnabled: false, onOrchestratorShellChange: vi.fn(),
    shellConfirmPolicy: "ask_all", onShellConfirmPolicyChange: vi.fn(),
    workspaceDir: "", onWorkspaceDirChange: vi.fn(),
    lanDiscoveryEnabled: false, onLanDiscoveryChange: vi.fn(),
    sshEnabled: false, onSshChange: vi.fn(),
    defaultReadEnabled: true, onDefaultReadChange: vi.fn(),
    voiceOutputEnabled: false, onVoiceOutputChange: vi.fn(),
    spawnMode: "auto", onSpawnModeChange: vi.fn(),
    ...over,
  };
}

describe("default-read setting", () => {
  test("the toggle reflects the value", () => {
    const { rerender } = render(<AdvancedSection {...props({ defaultReadEnabled: true })} />);
    expect(screen.getByTestId("default-read-toggle")).toBeChecked();
    rerender(<AdvancedSection {...props({ defaultReadEnabled: false })} />);
    expect(screen.getByTestId("default-read-toggle")).not.toBeChecked();
  });

  test("its description names the three folders it covers", () => {
    render(<AdvancedSection {...props()} />);
    const desc = screen.getByText(/Desktop/);
    expect(desc).toHaveTextContent(/Documents/);
    expect(desc).toHaveTextContent(/Downloads/);
  });
});

describe("the default is ON, end to end through the adapter", () => {
  test("an ABSENT backend key reads as enabled", () => {
    // The load-bearing default: a fresh install has no row, and that must mean
    // ON — the whole feature. A neighbour-style `=== "true"` would default it
    // OFF and silently undo the spec.
    expect(toUiSettings({} as never).defaultReadEnabled).toBe(true);
  });

  test('only an explicit "false" turns it off', () => {
    expect(toUiSettings({ default_read_enabled: "false" } as never).defaultReadEnabled).toBe(false);
    expect(toUiSettings({ default_read_enabled: "true" } as never).defaultReadEnabled).toBe(true);
  });
});
