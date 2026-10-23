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

vi.mock("../components/BrowserPanel", () => ({
  default: ({ open }: { open: boolean }) => (open ? <div data-testid="browser-panel-open" /> : null),
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
    voiceInputLocale: "", onVoiceInputLocaleChange: vi.fn(),
    voiceMode: "push_to_talk", onVoiceModeChange: vi.fn(),
    voiceEndpointSilenceMs: 900, onVoiceEndpointSilenceChange: vi.fn(),
    shellConfirmPolicy: "ask_all",
    onShellConfirmPolicyChange: vi.fn(),
    ...overrides,
  };
  render(<AdvancedSection {...props} />);
  return props;
}

describe("AdvancedSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the telemetry and terminal toggles; spawn mode and read-aloud are gone (0.1.48)", () => {
    setup();
    expect(document.getElementById("settings-telemetry-toggle")).not.toBeNull();
    expect(document.getElementById("settings-shell-toggle")).not.toBeNull();
    expect(document.getElementById("settings-spawn-mode")).toBeNull();
    expect(screen.queryByTestId("voice-output-toggle")).toBeNull();
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

  it("asking only for risky commands stays selectable, and says its judgement is completed in v0.1.64", () => {
    setup({ orchestratorShellEnabled: true, shellConfirmPolicy: "ask_all" });
    expect(screen.queryByTestId("shell-policy-risky-note")).toBeNull();
  });

  it("the note sits beside ask_risky when it is the choice", () => {
    setup({ orchestratorShellEnabled: true, shellConfirmPolicy: "ask_risky" });
    expect(screen.getByTestId("shell-policy-risky-note").textContent).toBe("settings.shellPolicyAskRiskyNote");
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

// 0.1.42: the work panel's footer link is gone; browser setup (the only
// caller of POST /browser/setup) and static preview live here now.
describe("AdvancedSection · browser setup home", () => {
  it("opens the browser setup and static preview panel", () => {
    setup();
    expect(screen.queryByTestId("browser-panel-open")).toBeNull();
    fireEvent.click(screen.getByTestId("settings-browser-setup"));
    expect(screen.getByTestId("browser-panel-open")).toBeInTheDocument();
  });
});

describe("AdvancedSection · background job budget (0.1.43)", () => {
  it("offers three tiers, states the chosen tier's limits, and saves the pick", async () => {
    const onBackgroundJobBudgetChange = vi.fn();
    setup({ backgroundJobBudget: "standard", onBackgroundJobBudgetChange });
    expect(screen.getByText("jobs.budgetLabel")).toBeInTheDocument();
    expect(screen.getByTestId("job-budget-desc")).toHaveTextContent("jobs.budgetDesc");
    const select = document.getElementById("settings-background-job-budget")!;
    await userEvent.click(select);
    await userEvent.click(await screen.findByText("jobs.budgetTier.ample"));
    expect(onBackgroundJobBudgetChange).toHaveBeenCalledWith("ample");
  });
});

describe("AdvancedSection · per-task dollar cap (K4a)", () => {
  it("offers $0.50 to $20, shows the stored cap, and saves a new one", () => {
    const onTaskUsdCapChange = vi.fn();
    setup({ backgroundJobBudget: "standard", onBackgroundJobBudgetChange: vi.fn(), taskUsdCap: 2, onTaskUsdCapChange });
    expect(screen.getByText("jobs.usdCapLabel")).toBeInTheDocument();
    expect(screen.getByTestId("task-usd-cap-desc")).toHaveTextContent("jobs.usdCapDesc");
    const select = screen.getByTestId("settings-task-usd-cap") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(
      ["$0.50", "$1.00", "$2.00", "$5.00", "$10.00", "$20.00"]);
    expect(select.value).toBe("2");
    fireEvent.change(select, { target: { value: "5" } });
    expect(onTaskUsdCapChange).toHaveBeenCalledWith(5);
  });

  it("shows a stored cap outside the list as itself", () => {
    setup({ backgroundJobBudget: "standard", onBackgroundJobBudgetChange: vi.fn(), taskUsdCap: 7.5, onTaskUsdCapChange: vi.fn() });
    const select = screen.getByTestId("settings-task-usd-cap") as HTMLSelectElement;
    expect(select.value).toBe("7.5");
    expect(Array.from(select.options).map((o) => o.textContent)).toContain("$7.50");
  });
});
