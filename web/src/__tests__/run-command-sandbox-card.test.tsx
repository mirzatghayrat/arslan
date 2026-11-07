/**
 * 0.1.51 P3: the run_command card's two sandbox questions, and the Advanced switch.
 * Leaving the sandbox is always said first in the card's 「风险」 row (SMART-8: the purpose leads the card); its
 * "In this conversation" (S4a) lets
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
  it("asking to leave says so, and its \"In this conversation\" is for this conversation", () => {
    const onConfirm = vi.fn();
    render(<RunCommandCard callId="c1" pretty="mv ~/Downloads/a.png ~/Pictures/" sandbox="outside" permKind="outside"
                           options={["once", "conversation"]} onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent("runcmd.purpose.move");
    expect(screen.getByTestId("ask-risk-row").textContent).toMatch(/^runcmd\.risk\.outside/);
    expect(screen.getByTestId("runcmd-sandbox-note")).toHaveTextContent("runcmd.sandboxOutsideNote");
    fireEvent.click(screen.getByTestId("runcmd-scope-conversation"));
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(screen.getByTestId("runcmd-run")).toHaveTextContent("runcmd.runOutside");
    expect(onConfirm).toHaveBeenCalledWith("c1", "conversation");
  });

  it("asking up front leads with Arslan's reason, marked as its words, and says first that it leaves the sandbox", () => {
    render(<RunCommandCard callId="c2" pretty="rm ~/Downloads/old.dmg" sandbox="outside" why="clean up Downloads"
                           rules={["delete-outside"]} reason="deletes files" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent("clean up Downloads");
    expect(screen.getByTestId("ask-purpose-from")).toHaveTextContent("kit.purposeFromArslan");
    expect(screen.getByTestId("ask-touches")).toHaveTextContent("~/Downloads/old.dmg");      // read by code, not said
    expect(screen.getByTestId("ask-risk-row").textContent).toMatch(/^runcmd\.risk\.outside.*runcmd\.risk\.rule\.delete-outside$/);
    expect(screen.getByTestId("ask-risk-row")).toHaveAttribute("data-level", "irreversible");
  });

  it("a background job's card offers this conversation too (S4a), and an ordinary card is unchanged", () => {
    render(<RunCommandCard callId="c3" pretty="mv a b" sandbox="outside" background permKind="outside"
                           options={["once", "conversation"]} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("runcmd-scope-conversation")).toBeInTheDocument();
    cleanup();
    render(<RunCommandCard callId="c4" pretty="git status" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent("runcmd.purpose.git");
    expect(screen.getByTestId("ask-purpose-from")).toHaveTextContent("kit.purposeFromCommand");
    expect(screen.getByTestId("ask-risk-row")).toHaveTextContent("runcmd.risk.sandboxed");
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
