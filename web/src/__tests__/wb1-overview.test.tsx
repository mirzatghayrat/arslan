/**
 * WB1-2 (v0.1.64, card docs/plans/0164/WB1-workbench.md): Overview, the workbench's default tab —
 * Environment, Deliverables (newest first, the one place they are listed), Context (the K4b rows) and
 * Connectors (only the servers that need something, then a count of the ready ones).
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { files, jobsApi, mcp, client, conv } = vi.hoisted(() => ({
  files: { list: vi.fn(), read: vi.fn(), stat: vi.fn(), open: vi.fn(), reveal: vi.fn(), home: vi.fn(), conversationFiles: vi.fn(), changes: vi.fn() },
  jobsApi: { list: vi.fn(), stop: vi.fn() },
  mcp: { listMcpServers: vi.fn(), reconnectMcpServer: vi.fn() },
  client: { fetchProviderModels: vi.fn(), updateProviderConfig: vi.fn(), api: { runCheckpoint: vi.fn() } },
  conv: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
}));
vi.mock("../api/files", () => ({ filesApi: files }));
vi.mock("../api/tasks", () => ({ backgroundJobsApi: jobsApi }));
vi.mock("../api/mcp", () => mcp);
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), ...client }));
vi.mock("../api/conversationModel", () => ({ conversationModelApi: conv }));
vi.mock("../components/BrowserReader", () => ({ default: () => <div data-testid="browser-reader" /> }));

import type { McpServer, ProviderConfig, StoredArtifact } from "../api/client.types";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { useSettingsStore } from "../stores/settingsStore";
import { useWorkbench } from "../stores/workbenchStore";
import { _resetChipCatalogs, ringRows } from "../components/models/ConversationModelChip";
import Workbench from "../components/workbench/Workbench";
import { connectorSummary, newestFirst } from "../components/workbench/OverviewTab";

const cfg = { id: 1, provider: "deepseek", model: "deepseek-chat", is_primary: true, label: "DeepSeek" } as ProviderConfig;
const PARTS = { system: 1000, tools: 3000, context: 500, history: 4000, turn: 1500 };
const art = (title: string, created_at: string | undefined, i: number) => ({ kind: "file", run_id: 9, filename: `run_9_${i}_${title}`,
  title, bytes: 2048, sha256: "b".repeat(64), media_type: "text/plain", url: "", created_at }) as StoredArtifact & { created_at?: string };
const server = (id: number, shown: string) => ({ id, label: `S${id}`, command: "x", args: [], env: {}, status: "", shown }) as McpServer;
const onOpenSettings = vi.fn(), onOpenCapabilities = vi.fn();
const mount = () => render(<Workbench conversationId="c1" taskId={null} temporary={false}
  models={{ configs: [cfg], llmProviders: [], onSetDefault: vi.fn() }} onOpenSettings={onOpenSettings} onOpenCapabilities={onOpenCapabilities} />);

beforeEach(() => {
  _resetChipCatalogs();
  useArslanStore.setState(initialArslanState(), true);
  useWorkbench.setState({ open: false, tab: "overview", reader: null, folder: null });
  useSettingsStore.setState({ settings: { phone_bridge_enabled: true } } as never);
  files.home.mockResolvedValue({ path: "~/Arslan", project: null });
  files.conversationFiles.mockResolvedValue({ files: [] });
  files.list.mockResolvedValue({ path: "~/Arslan", root: "~/Arslan", crumbs: [], total: 0, more: false, entries: [] });
  jobsApi.list.mockResolvedValue({ jobs: [] });
  mcp.listMcpServers.mockResolvedValue([]);
  mcp.reconnectMcpServer.mockResolvedValue({ ok: true });
  client.fetchProviderModels.mockResolvedValue({ models: [{ id: "deepseek-chat", context_window: 64000, capabilities: ["tools"] }] });
  conv.get.mockResolvedValue({ choice: null });
  files.changes.mockResolvedValue({ turns: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Overview", () => {
  it("is the first tab and the one shown when the panel opens", async () => {
    useWorkbench.getState().show();
    mount();
    expect(within(screen.getByRole("tablist")).getAllByRole("tab")[0]).toHaveAttribute("data-testid", "workbench-tab-overview");
    expect(await screen.findByTestId("overview-tab")).toBeInTheDocument();
  });

  it("Environment: the model chip, the folder with Show in Finder, and the iPhone remote's state opening Settings", async () => {
    useWorkbench.getState().show("overview");
    mount();
    const env = await screen.findByTestId("overview-environment");
    expect(within(env).getByTestId("model-chip")).toHaveTextContent("deepseek-chat");
    expect(within(env).queryByTestId("context-ring")).toBeNull();                   // the ring is Overview's Context section
    fireEvent.click(await within(env).findByTestId("overview-reveal"));
    expect(files.reveal).toHaveBeenCalledWith("~/Arslan");
    const bridge = within(env).getByTestId("overview-bridge");
    expect(bridge).toHaveTextContent("workbench.bridgeOn");
    fireEvent.click(bridge);
    expect(onOpenSettings).toHaveBeenCalledWith("connections");
  });

  it("Deliverables: every file this conversation made, newest first; a click opens the reader", async () => {
    files.conversationFiles.mockResolvedValue({ files: [art("old.md", "2026-10-29T08:00:00", 1), art("new.md", "2026-10-30T09:00:00", 2),
      art("mid.md", "2026-10-30T08:00:00", 3)] });
    useWorkbench.getState().show("overview");
    mount();
    const list = await screen.findByTestId("conv-files");
    expect(within(list).getAllByRole("button").map((b) => b.querySelector(".truncate")?.textContent)).toEqual(["new.md", "mid.md", "old.md"]);
    fireEvent.click(within(list).getAllByRole("button")[0]);
    expect(useWorkbench.getState().reader).toMatchObject({ kind: "artifact", file: { title: "new.md" } });
  });

  it("Deliverables says so when there is nothing yet, and Working folder no longer lists them", async () => {
    useWorkbench.getState().show("overview");
    mount();
    expect(await screen.findByTestId("overview-deliverables")).toHaveTextContent("workbench.noConvFiles");
    fireEvent.click(screen.getByTestId("workbench-tab-files"));
    await screen.findByTestId("files-tab");
    expect(screen.queryByTestId("conv-files")).toBeNull();
  });

  it("Context: the five rows are ringRows() for the last reply, against the model's window", async () => {
    useArslanStore.setState({ items: [{ kind: "message", id: "a", role: "arslan", text: "hi", usage: { last_input: 48000, context_parts: PARTS } }] } as never);
    useWorkbench.getState().show("overview");
    mount();
    const ctx = await screen.findByTestId("overview-context");
    expect(ctx).toHaveTextContent('models.context:{"pct":75}');
    expect(ctx).toHaveTextContent("48,000 / 64,000");
    for (const row of ringRows(PARTS, 48000)) {
      const li = within(ctx).getByTestId(`overview-part-${row.key}`);
      expect(li).toHaveTextContent(`models.about:{"value":"${row.tokens.toLocaleString("en")}"}`);
      expect(li).toHaveTextContent(`${row.pct}%`);
    }
    expect(ctx).toHaveTextContent("models.contextEstimated");
  });

  it("Context is left out until a reply has reported its input", async () => {
    useWorkbench.getState().show("overview");
    mount();
    await screen.findByTestId("overview-deliverables");
    expect(screen.queryByTestId("overview-context")).toBeNull();
  });

  it("Connectors: only the ones that need something, then how many others are ready", async () => {
    mcp.listMcpServers.mockResolvedValue([server(1, "ready"), server(2, "needs_auth"), server(3, "failed"), server(4, "ready"),
      server(5, "off"), server(6, "starting"), server(7, "parked"), server(8, "ready")]);
    useWorkbench.getState().show("overview");
    mount();
    const con = await screen.findByTestId("overview-connectors");
    expect(within(con).getAllByTestId(/^overview-connector-/).map((li) => li.getAttribute("data-testid")))
      .toEqual(["overview-connector-2", "overview-connector-3", "overview-connector-7"]);
    expect(within(con).getByTestId("overview-connector-2")).toHaveTextContent("workbench.needsSignIn");
    expect(within(con).getByTestId("overview-connector-3")).toHaveTextContent("workbench.cantConnect");
    expect(within(con).getByTestId("overview-connectors-ok")).toHaveTextContent('workbench.othersOk:{"count":3}');
    fireEvent.click(within(con).getByRole("button", { name: "workbench.signIn" }));
    expect(onOpenCapabilities).toHaveBeenCalled();                                   // sign-in stays where its URL is minted
    await act(async () => { fireEvent.click(within(con).getByTestId("overview-retry-3")); });
    await waitFor(() => expect(mcp.reconnectMcpServer).toHaveBeenCalledWith(3));
    await waitFor(() => expect(mcp.listMcpServers).toHaveBeenCalledTimes(2));       // reloaded after the retry
  });

  it("Connectors is left out when there are no servers", async () => {
    useWorkbench.getState().show("overview");
    mount();
    await screen.findByTestId("overview-deliverables");
    await waitFor(() => expect(mcp.listMcpServers).toHaveBeenCalled());
    expect(screen.queryByTestId("overview-connectors")).toBeNull();
  });
});

describe("Changes (WB1-3)", () => {
  const turns = [
    { run_id: 12, at: "2026-10-30T09:31:00", undone: false, paths: [
      { folder: "~/Arslan", path: "tm-exclusions.txt", kind: "edited" }, { folder: "~/Arslan", path: "drive-check.png", kind: "made" }] },
    { run_id: 11, at: "2026-10-30T09:12:00", undone: true, paths: [{ folder: "~/Arslan", path: "old.md", kind: "deleted" }] },
  ];

  it("lists each turn's paths with what happened to them, and offers undo only where it can", async () => {
    files.changes.mockResolvedValue({ turns });
    useWorkbench.getState().show("overview");
    mount();
    const section = await screen.findByTestId("overview-changes");
    expect(files.changes).toHaveBeenCalledWith("c1");
    expect(section).toHaveTextContent("workbench.chNote");
    const t12 = within(section).getByTestId("overview-turn-12");
    expect(t12).toHaveTextContent("workbench.edited");
    expect(t12).toHaveTextContent("tm-exclusions.txt");
    expect(t12).toHaveTextContent("workbench.made");
    expect(within(section).getByTestId("overview-turn-11")).toHaveTextContent("workbench.deleted");
    expect(within(section).queryByTestId("overview-undo-11")).toBeNull();            // already undone
    expect(within(section).getByTestId("overview-undo-12")).toHaveTextContent("process.undoTurn");
  });

  it("opens today's undo sheet for that turn", async () => {
    files.changes.mockResolvedValue({ turns });
    client.api.runCheckpoint.mockResolvedValue({ exists: true, changed: 1, created: 1, skipped: [], excluded: [], overlap: [],
      later: [], running: false, restored_at: null, expires_at: "2026-11-06T00:00:00", conversation: false });
    useWorkbench.getState().show("overview");
    mount();
    fireEvent.click(await screen.findByTestId("overview-undo-12"));
    await waitFor(() => expect(client.api.runCheckpoint).toHaveBeenCalledWith(12));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("is left out when no turn changed anything", async () => {
    useWorkbench.getState().show("overview");
    mount();
    await screen.findByTestId("overview-deliverables");
    await waitFor(() => expect(files.changes).toHaveBeenCalled());
    expect(screen.queryByTestId("overview-changes")).toBeNull();
  });
});

describe("Connectors with nothing to say", () => {
  it("is left out when every server is off or starting (#530 review)", async () => {
    mcp.listMcpServers.mockResolvedValue([server(1, "off"), server(2, "starting")]);
    useWorkbench.getState().show("overview");
    mount();
    await waitFor(() => expect(mcp.listMcpServers).toHaveBeenCalled());
    await screen.findByTestId("overview-deliverables");
    expect(screen.queryByTestId("overview-connectors")).toBeNull();
  });
});

describe("the helpers", () => {
  it("newestFirst sorts by creation time and keeps the newest of untimed ones first", () => {
    const a = art("a", undefined, 1), b = art("b", undefined, 2), c = art("c", "2026-10-30T09:00:00", 3);
    expect(newestFirst([a, b, c]).map((f) => f.title)).toEqual(["c", "b", "a"]);
  });

  it("connectorSummary never counts a switched-off or starting server", () => {
    const s = connectorSummary([server(1, "off"), server(2, "starting"), server(3, "ready")]);
    expect(s.needs).toEqual([]);
    expect(s.readyCount).toBe(1);
  });
});
