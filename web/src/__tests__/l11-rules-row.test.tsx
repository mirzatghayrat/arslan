/**
 * L11 (v0.1.64): the rules a conversation follows, as one row in Overview's Environment (each file opening in the
 * reader), and the "Follow folder rules" switch in Settings → Advanced. Read only: since the user's L11 (b) decision
 * (2026-11-02), Arslan never offers to write a rules file and Overview never edits one; a correction that recurs in a
 * folder becomes a practice in Arslan's own memory.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { files, jobsApi, mcp, client, conv, toast } = vi.hoisted(() => ({
  files: { list: vi.fn(), read: vi.fn(), stat: vi.fn(), open: vi.fn(), reveal: vi.fn(), home: vi.fn(), conversationFiles: vi.fn(),
    changes: vi.fn() },
  jobsApi: { list: vi.fn(), stop: vi.fn() },
  mcp: { listMcpServers: vi.fn(), reconnectMcpServer: vi.fn() },
  client: { fetchProviderModels: vi.fn(), updateProviderConfig: vi.fn(), api: { runCheckpoint: vi.fn(), undoTurn: vi.fn() } },
  conv: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
  toast: vi.fn(),
}));
vi.mock("../api/files", () => ({ filesApi: files }));
vi.mock("../api/tasks", () => ({ backgroundJobsApi: jobsApi }));
vi.mock("../api/mcp", () => mcp);
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), ...client }));
vi.mock("../api/conversationModel", () => ({ conversationModelApi: conv }));
vi.mock("../components/BrowserReader", () => ({ default: () => <div /> }));
vi.mock("../components/kit", async (orig) => ({ ...(await orig<object>()), toast }));

import { lessonsApi } from "../api/lessons";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { useSettingsStore } from "../stores/settingsStore";
import { useWorkbench } from "../stores/workbenchStore";
import Workbench from "../components/workbench/Workbench";
import AdvancedSection from "../components/settings/AdvancedSection";

const FILE = "~/Projects/photo/AGENTS.md";
const RLO = String.fromCharCode(0x202e), FSI = String.fromCharCode(0x2068), PDI = String.fromCharCode(0x2069);
const REORDER = /[\u202A-\u202E\u2066\u2067]/;

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  useWorkbench.setState({ open: false, tab: "overview", reader: null, folder: null });
  useSettingsStore.setState({ settings: {} } as never);
  files.home.mockResolvedValue({ path: "~/Projects/photo", project: null });
  files.conversationFiles.mockResolvedValue({ files: [] });
  files.changes.mockResolvedValue({ turns: [] });
  jobsApi.list.mockResolvedValue({ jobs: [] });
  mcp.listMcpServers.mockResolvedValue([]);
  conv.get.mockResolvedValue({ choice: null });
  toast.mockClear();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("no rules card", () => {
  it("a rule_offer frame from an older server adds nothing to the conversation", () => {
    useArslanStore.getState().handleFrame({ type: "rule_offer", lesson_id: 7, text: "reports → 24-hour times", file: FILE } as never);
    expect(useArslanStore.getState().items).toEqual([]);
  });

  it("Overview lists a file with no Remove, even when an older server still sends lines", async () => {
    vi.spyOn(lessonsApi, "folderRules").mockResolvedValue({ enabled: true, files: [
      { file: FILE, text: "- 24-hour\n", added: [{ lesson_id: 7, line: "24-hour" }] } as never] });
    useWorkbench.getState().show("overview");
    render(<Workbench conversationId="c1" taskId={null} temporary={false} />);
    const row = await screen.findByTestId("overview-rules");
    fireEvent.click(within(row).getByTestId("overview-rules-toggle"));
    expect(within(row).getAllByTestId("overview-rules-file")).toHaveLength(1);
    expect(within(row).queryByTestId("overview-rules-added")).toBeNull();
    expect(within(row).queryByRole("button", { name: "workbench.ruleRemove" })).toBeNull();
  });
});

describe("Overview's row", () => {
  const mount = () => render(<Workbench conversationId="c1" taskId={null} temporary={false} />);

  it("names how many files the conversation follows; each opens in the reader with its text", async () => {
    vi.spyOn(lessonsApi, "folderRules").mockResolvedValue({ enabled: true, files: [
      { file: "~/Projects/AGENTS.md", text: "outer" }, { file: FILE, text: "inner" }] });
    useWorkbench.getState().show("overview");
    mount();
    const row = await screen.findByTestId("overview-rules");
    expect(row).toHaveTextContent('workbench.rulesRow:{"count":2}');
    fireEvent.click(within(row).getByTestId("overview-rules-toggle"));
    expect(row).toHaveTextContent("workbench.rulesNote");
    fireEvent.click(within(row).getByRole("button", { name: new RegExp(FILE.replace(/[.~/]/g, "\\$&")) }));
    expect(useWorkbench.getState().reader).toEqual({ kind: "text", name: FILE, text: "inner" });
  });

  it("W9: Overview's file names are isolated", async () => {
    vi.spyOn(lessonsApi, "folderRules").mockResolvedValue({ enabled: true, files: [
      { file: `~/Pro${RLO}jects/AGENTS.md`, text: "x" }] });
    useWorkbench.getState().show("overview");
    mount();
    const row = await screen.findByTestId("overview-rules");
    fireEvent.click(within(row).getByTestId("overview-rules-toggle"));
    const file = within(row).getByTestId("overview-rules-file");
    expect(file.textContent).not.toMatch(REORDER);
    expect(file.textContent).toContain(`${FSI}~/Projects/AGENTS.md${PDI}`);
  });

  it("switched off says so; with no rules files there is no row", async () => {
    const spy = vi.spyOn(lessonsApi, "folderRules").mockResolvedValue({ enabled: false, files: [] });
    useWorkbench.getState().show("overview");
    const view = mount();
    expect(await screen.findByTestId("overview-rules")).toHaveTextContent("workbench.rulesOff");
    view.unmount();
    // A mount fetches again when the folder (`home`) arrives, so how many calls one mount makes depends on timing
    // (a fixed count was a flake on a loaded CI runner). What matters: the new mount asked, and once every answer
    // is in, there is no row.
    const before = spy.mock.calls.length;
    spy.mockResolvedValue({ enabled: true, files: [] });
    mount();
    await waitFor(() => expect(spy.mock.calls.length).toBeGreaterThan(before));
    await act(async () => { await Promise.all(spy.mock.results.map((r) => r.value)); });
    expect(screen.queryByTestId("overview-rules")).toBeNull();
  });
});

describe("Settings → Advanced", () => {
  it("the switch shows the value and says when it changes", () => {
    const onChange = vi.fn();
    const props = {
      telemetry: false, onTelemetryChange: vi.fn(), orchestratorShellEnabled: false, onOrchestratorShellChange: vi.fn(),
      shellConfirmPolicy: "ask_all", onShellConfirmPolicyChange: vi.fn(), workspaceDir: "", onWorkspaceDirChange: vi.fn(),
      lanDiscoveryEnabled: false, onLanDiscoveryChange: vi.fn(), sshEnabled: false, onSshChange: vi.fn(),
      defaultReadEnabled: true, onDefaultReadChange: vi.fn(), voiceInputLocale: "", onVoiceInputLocaleChange: vi.fn(),
      voiceMode: "push_to_talk", onVoiceModeChange: vi.fn(), voiceEndpointSilenceMs: 900, onVoiceEndpointSilenceChange: vi.fn(),
    } as unknown as React.ComponentProps<typeof AdvancedSection>;
    const { rerender } = render(<AdvancedSection {...props} folderRulesEnabled onFolderRulesChange={onChange} />);
    const toggle = screen.getByTestId("folder-rules-toggle");
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(false);
    rerender(<AdvancedSection {...props} folderRulesEnabled={false} onFolderRulesChange={onChange} />);
    expect(screen.getByTestId("folder-rules-toggle")).not.toBeChecked();
  });
});
