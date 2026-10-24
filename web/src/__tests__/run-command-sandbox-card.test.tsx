/**
 * 0.1.51 P3: the run_command card's two sandbox questions, and the Advanced switch.
 * Leaving the sandbox is always said first on the card; its "In this conversation" (S4a) lets
 * every command of the conversation out, never "don't ask again for this kind of command".
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../components/settings/TerminalRulesPanel", () => ({ default: () => null }));
vi.mock("../components/BrowserPanel", () => ({ default: () => null }));

import RunCommandCard from "../components/RunCommandCard";
import AdvancedSection from "../components/settings/AdvancedSection";

afterEach(() => cleanup());

describe("RunCommandCard sandbox questions", () => {
  it("a stopped command says so, offers a re-run outside, and its \"In this conversation\" is for this conversation", () => {
    const onConfirm = vi.fn();
    render(<RunCommandCard callId="c1" pretty="mv ~/Downloads/a.png ~/Pictures/" sandbox="retry" permKind="outside"
                           options={["once", "conversation"]} onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.getByText("runcmd.sandboxRetryLabel")).toBeInTheDocument();
    expect(screen.getByTestId("runcmd-sandbox-note")).toHaveTextContent("runcmd.sandboxRetryNote");
    fireEvent.click(screen.getByTestId("runcmd-scope-conversation"));
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(screen.getByTestId("runcmd-run")).toHaveTextContent("runcmd.runOutside");
    expect(onConfirm).toHaveBeenCalledWith("c1", "conversation");
  });

  it("asking up front shows Arslan's reason and the command's own reason", () => {
    render(<RunCommandCard callId="c2" pretty="rm ~/Downloads/old.dmg" sandbox="outside" why="clean up Downloads"
                           reason="deletes files" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText("runcmd.sandboxOutsideLabel")).toBeInTheDocument();
    expect(screen.getByTestId("runcmd-why")).toHaveTextContent("clean up Downloads");
    expect(screen.getByText("deletes files")).toBeInTheDocument();
  });

  it("a background job's card offers this conversation too (S4a), and an ordinary card is unchanged", () => {
    render(<RunCommandCard callId="c3" pretty="mv a b" sandbox="retry" background permKind="outside"
                           options={["once", "conversation"]} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("runcmd-scope-conversation")).toBeInTheDocument();
    cleanup();
    render(<RunCommandCard callId="c4" pretty="git status" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText("runcmd.label")).toBeInTheDocument();
    expect(screen.queryByTestId("runcmd-sandbox-note")).toBeNull();
    expect(screen.getByTestId("runcmd-run")).toHaveTextContent("runcmd.run");
  });
});

describe("Advanced › Run commands in a sandbox", () => {
  const base = {
    telemetry: false, onTelemetryChange: vi.fn(), orchestratorShellEnabled: true, onOrchestratorShellChange: vi.fn(),
    workspaceDir: "", onWorkspaceDirChange: vi.fn(), lanDiscoveryEnabled: false, onLanDiscoveryChange: vi.fn(),
    sshEnabled: false, onSshChange: vi.fn(), defaultReadEnabled: true, onDefaultReadChange: vi.fn(),
    voiceInputLocale: "", onVoiceInputLocaleChange: vi.fn(), voiceMode: "push_to_talk" as const,
    onVoiceModeChange: vi.fn(), voiceEndpointSilenceMs: 900, onVoiceEndpointSilenceChange: vi.fn(),
    shellConfirmPolicy: "ask_risky" as const, onShellConfirmPolicyChange: vi.fn(),
  };

  it("is on unless turned off, reports changes, and hides with the terminal", () => {
    const onChange = vi.fn();
    const { rerender } = render(<AdvancedSection {...base} onTerminalSandboxChange={onChange} />);
    const toggle = screen.getByTestId("settings-terminal-sandbox-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(false);
    rerender(<AdvancedSection {...base} terminalSandboxEnabled={false} onTerminalSandboxChange={onChange} />);
    expect((screen.getByTestId("settings-terminal-sandbox-toggle") as HTMLInputElement).checked).toBe(false);
    rerender(<AdvancedSection {...base} orchestratorShellEnabled={false} />);
    expect(screen.queryByTestId("settings-terminal-sandbox-toggle")).toBeNull();
  });
});
