/**
 * L11-2 (v0.1.64; the user's L11-0 picks, 2026-10-31): "Make this a rule for this folder?" in the conversation after the
 * same correction twice (Add / Not now; Remove after Add), the rules a conversation follows as one row in Overview's
 * Environment (each file opening in the reader), and the "Follow folder rules" switch in Settings → Advanced.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import { ApiError } from "../api/client";
import { toUiMessages } from "../api/adapters";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { useSettingsStore } from "../stores/settingsStore";
import { useWorkbench } from "../stores/workbenchStore";
import RuleOfferCard from "../components/RuleOfferCard";
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

describe("the card in the conversation", () => {
  it("a rule_offer frame becomes one card, not a bubble", () => {
    useArslanStore.getState().handleFrame({ type: "rule_offer", lesson_id: 7, text: "reports → 24-hour times", file: FILE } as never);
    const items = useArslanStore.getState().items;
    expect(items[items.length - 1]).toMatchObject({ kind: "rule_offer", content: "reports → 24-hour times",
      ruleOffer: { lessonId: 7, file: FILE } });
    const [msg] = toUiMessages(items.slice(-1));
    expect(msg.ruleOffer).toEqual({ lessonId: 7, file: FILE });
  });

  it("Add writes it (the user's click), Open shows the file, Remove takes it back", async () => {
    const rule = vi.spyOn(lessonsApi, "rule").mockResolvedValueOnce({ state: "added", file: FILE })
      .mockResolvedValueOnce({ state: "removed", file: FILE });
    render(<RuleOfferCard lessonId={7} file={FILE} text="reports → 24-hour times" conversationId="c1" />);
    expect(screen.getByTestId("rule-offer")).toHaveTextContent("reports → 24-hour times");
    expect(screen.getByTestId("rule-offer")).toHaveTextContent(FILE);
    fireEvent.click(screen.getByTestId("rule-offer-add"));
    expect(await screen.findByTestId("rule-offer-added")).toHaveTextContent("workbench.ruleAdded");
    expect(rule).toHaveBeenCalledWith(7, "c1", "add");
    fireEvent.click(screen.getByRole("button", { name: /workbench\.ruleOpen/ }));
    expect(useWorkbench.getState().reader).toEqual({ kind: "path", path: FILE });
    fireEvent.click(screen.getByTestId("rule-offer-remove"));
    expect(await screen.findByTestId("rule-offer-removed")).toBeInTheDocument();
    expect(rule).toHaveBeenLastCalledWith(7, "c1", "remove");
  });

  it("Not now is one click; a failure says so and keeps the buttons", async () => {
    vi.spyOn(lessonsApi, "rule").mockRejectedValueOnce(new Error("409")).mockResolvedValueOnce({ state: "skipped" });
    render(<RuleOfferCard lessonId={7} file={FILE} text="x" conversationId="c1" />);
    fireEvent.click(screen.getByTestId("rule-offer-add"));
    expect(await screen.findByTestId("rule-offer-failed")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("rule-offer-skip"));
    expect(await screen.findByTestId("rule-offer-skipped")).toHaveTextContent("workbench.ruleSkipped");
  });
});

describe("the card's text is isolated, and says why Add was refused (#603 review)", () => {
  it("W7, W8: the lesson's words and the file name are isolated; no reordering control is left", () => {
    render(<RuleOfferCard lessonId={7} file={`~/Pro${RLO}jects/AGENTS.md`} text={`use ${RLO}24-hour`} conversationId="c1" />);
    const card = screen.getByTestId("rule-offer");
    expect(card.textContent).not.toMatch(REORDER);
    expect(card.textContent).toContain(`${FSI}use 24-hour${PDI}`);
    expect(card.textContent).toContain(`${FSI}~/Projects/AGENTS.md${PDI}`);
  });

  it.each([["rules_file_full", "rule-offer-full", "workbench.ruleFull"], ["lesson_changed", "rule-offer-changed", "workbench.ruleChanged"]])(
    "a %s refusal says so", async (code, testid, key) => {
      vi.spyOn(lessonsApi, "rule").mockRejectedValue(new ApiError(code, 409, code));
      render(<RuleOfferCard lessonId={7} file={FILE} text="x" conversationId="c1" />);
      fireEvent.click(screen.getByTestId("rule-offer-add"));
      expect(await screen.findByTestId(testid)).toHaveTextContent(key);
      if (code === "lesson_changed") expect(screen.queryByTestId("rule-offer-add")).toBeNull();   // offered again later
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

  it("F3: a line the card added is listed with Remove, which takes it back out and reloads the row", async () => {
    let removed = false;
    const list = vi.spyOn(lessonsApi, "folderRules").mockImplementation(async () => (removed
      ? { enabled: true, files: [{ file: FILE, text: "", added: [] }] }
      : { enabled: true, files: [{ file: FILE, text: "- 24-hour\n", added: [{ lesson_id: 7, line: `use ${RLO}24-hour` }] }] }));
    const rule = vi.spyOn(lessonsApi, "removeFolderRule").mockImplementation(async () => {
      removed = true; return { state: "removed", file: FILE, in_file: true }; });
    useWorkbench.getState().show("overview");
    mount();
    const row = await screen.findByTestId("overview-rules");
    fireEvent.click(within(row).getByTestId("overview-rules-toggle"));
    const added = await within(row).findByTestId("overview-rules-added");
    expect(added.textContent).not.toMatch(REORDER);                              // W9: isolated too
    expect(added.textContent).toContain(`${FSI}use 24-hour${PDI}`);
    fireEvent.click(within(added).getByRole("button", { name: "workbench.ruleRemove" }));
    await waitFor(() => expect(rule).toHaveBeenCalledWith("c1", FILE, 7, `use ${RLO}24-hour`));   // L11-3a: the record
    const before = list.mock.calls.length;
    await waitFor(() => expect(list.mock.calls.length).toBeGreaterThan(before));
    await waitFor(() => expect(screen.queryByTestId("overview-rules-added")).toBeNull());
  });

  it("L11-3a: two lines under one lesson id are both listed, and each Remove names its own line", async () => {
    vi.spyOn(lessonsApi, "folderRules").mockResolvedValue({ enabled: true, files: [{ file: FILE, text: "- a\n- b\n",
      added: [{ lesson_id: 7, line: "a" }, { lesson_id: 7, line: "b" }] }] });
    const remove = vi.spyOn(lessonsApi, "removeFolderRule").mockResolvedValue({ state: "removed", file: FILE, in_file: true });
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    useWorkbench.getState().show("overview");
    mount();
    const row = await screen.findByTestId("overview-rules");
    fireEvent.click(within(row).getByTestId("overview-rules-toggle"));
    const added = await within(row).findAllByTestId("overview-rules-added");
    expect(added.map((a) => a.textContent)).toEqual([expect.stringContaining("a"), expect.stringContaining("b")]);
    fireEvent.click(within(added[1]).getByRole("button", { name: "workbench.ruleRemove" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("c1", FILE, 7, "b"));
    expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key/);          // #621 review, F7: the row key
    expect(toast).not.toHaveBeenCalled();
  });

  it("#621 F3: a line that had changed in the file says so", async () => {
    vi.spyOn(lessonsApi, "folderRules").mockResolvedValue({ enabled: true, files: [{ file: FILE, text: "- a\r\n",
      added: [{ lesson_id: 7, line: "a" }] }] });
    vi.spyOn(lessonsApi, "removeFolderRule").mockResolvedValue({ state: "removed", file: FILE, in_file: false });
    useWorkbench.getState().show("overview");
    mount();
    const row = await screen.findByTestId("overview-rules");
    fireEvent.click(within(row).getByTestId("overview-rules-toggle"));
    fireEvent.click(within(await within(row).findByTestId("overview-rules-added")).getByRole("button", { name: "workbench.ruleRemove" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("workbench.ruleNotInFile"));
  });

  it("#621 R2: the live card's Remove says when the line had changed in the file", async () => {
    vi.spyOn(lessonsApi, "rule").mockResolvedValueOnce({ state: "added", file: FILE })
      .mockResolvedValueOnce({ state: "removed", file: FILE, in_file: false });
    render(<RuleOfferCard lessonId={7} file={FILE} text="reports" conversationId="c1" />);
    fireEvent.click(screen.getByTestId("rule-offer-add"));
    fireEvent.click(await screen.findByTestId("rule-offer-remove"));
    expect(await screen.findByTestId("rule-offer-kept")).toHaveTextContent("workbench.ruleNotInFile");
  });

  it("#621 F7: Remove posts the file, the lesson and the line to the conversation's endpoint", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ state: "removed", file: FILE, in_file: true }), { status: 200 }));
    expect(await lessonsApi.removeFolderRule("c 1", FILE, 7, "use 24-hour")).toEqual({ state: "removed", file: FILE, in_file: true });
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/conversations\/c%201\/folder-rules\/remove$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ file: FILE, lesson_id: 7, line: "use 24-hour" });
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
    spy.mockResolvedValue({ enabled: true, files: [] });
    mount();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
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
