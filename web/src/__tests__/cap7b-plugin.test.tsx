// CAP7b, the web half (the boards the user approved: Main, Risky, Refused, Group): a plugin's install card names every
// part and what each connection starts with; a known vulnerability in one connection makes "Don't install" the safe
// answer; a refused plugin is one plain line, no card; Capabilities shows a Plugins group, once one is installed, each
// plugin one row with one switch and one delete. Real strings (en); every name below is invented.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "../i18n";
import CapabilityProposeCard from "../components/capabilities/CapabilityProposeCard";
import CapabilityResultLine from "../components/capabilities/CapabilityResultLine";
import CapabilitySwitches from "../components/CapabilitySwitches";
import { capabilitiesApi, type CapabilityRow } from "../api/capabilities";
import type { Advisory, CapabilityCard, PluginConnection, Vulns } from "../api/client.types";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { toUiMessages } from "../api/adapters";

vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn().mockResolvedValue([]), listMcpTools: vi.fn().mockResolvedValue([]),
}));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const checked = (over: Partial<Extract<Vulns, { state: "checked" }>> = {}): Vulns =>
  ({ state: "checked", source: "OSV.dev", packages: 38, asked: 38, complete: true, count: 0, highest: null,
     own_highest: null, deps_highest: null, own: [], own_more: 0, deps: [], deps_more: 0, ...over });
const adv = (id: string): Advisory => ({ id, ids: [id], severity: "HIGH", summary: "reads outside its folder",
  loaded: true, fixed: ["1.4.3"] });
const remote: PluginConnection = { name: "tickets", runtime: "remote", package: null, version: null,
  remote_host: "https://mcp.example.dev/mcp", network: true, arguments: [], env: {},
  headers: { "X-Team": "core", "X-Api-Key": "●●●●" }, keys: ["Authorization"], vulns: { state: "skipped", why: "remote" } };
const local: PluginConnection = { name: "md-tools", runtime: "node", package: { identifier: "md-tools", version: "1.4.2" },
  version: "1.4.2", remote_host: null, network: false, arguments: ["--read-only"], env: { MODE: "fast" }, headers: {},
  keys: [], vulns: checked() };
const PLUGIN: CapabilityCard = {
  kind: "plugin", name: "notes-kit", summary: "Writes release notes", source_url: "https://github.com/example/notes-kit",
  repo: "example/notes-kit", version: null, license: { spdx: "MIT", read_from: "LICENSE" }, stars: 412, pushed_days: 6,
  runtime: "plugin", runtime_download: null, remote_host: null, network: false, folders: [],
  keys: [{ name: "Authorization", secret: true, required: true, description: "Bearer ${TOKEN}" }],
  why: "Release notes need a method", retry: "write the release notes", commit: "8f3a1c20d4e7a1b2c3d4e5f60718293a4b5c6d7e",
  publisher: { kind: "github", value: "example" },
  skills: [
    { key: "notes", name: "notes", summary: "Writes notes", scripts: ["fmt.py", "lint.py"], references: [],
      hidden: { count: 0, runs: [], more: 0 } },
    { key: "style", name: "style", summary: "A style", scripts: [], references: [], hidden: { count: 0, runs: [], more: 0 } }],
  connections: [remote, local],
};

function show(card: CapabilityCard = PLUGIN) {
  const onConfirm = vi.fn(), onCancel = vi.fn();
  render(<CapabilityProposeCard card={card} callId="c1" onConfirm={onConfirm} onCancel={onCancel} />);
  return { onConfirm, onCancel };
}

describe("the plugin card (board Main)", () => {
  it("names every part, and what each connection starts with, as the server sends it", () => {
    show();
    expect(screen.getByTestId("capability-card")).toHaveTextContent("Add the plugin");
    expect(screen.getByTestId("capability-card-source")).toHaveTextContent("example/notes-kit");
    expect(screen.getByTestId("capability-card-source")).toHaveTextContent("commit 8f3a1c20d4e7");
    const parts = screen.getAllByTestId("plugin-part");
    expect(parts.map(p => p.dataset.kind)).toEqual(["skill", "skill", "connection", "connection"]);
    expect(parts[0]).toHaveTextContent("2 scripts, run in the offline sandbox");
    expect(parts[1]).toHaveTextContent("Instructions only.");
    expect(parts[2]).toHaveTextContent("Runs on mcp.example.dev");
    expect(parts[2]).toHaveTextContent("X-Team: core");
    expect(parts[2]).toHaveTextContent("X-Api-Key: ●●●●");          // a fixed credential, masked by the server
    expect(parts[2]).toHaveTextContent("Authorization");             // the key it gets, typed below
    expect(parts[3]).toHaveTextContent("md-tools 1.4.2");
    expect(parts[3]).toHaveTextContent("no network");
    expect(parts[3]).toHaveTextContent("--read-only");
    expect(parts[3]).toHaveTextContent("MODE=fast");
    expect(screen.getByTestId("capability-card")).toHaveTextContent("each connection is tested once. If one part doesn’t pass, nothing stays");
    expect(screen.getByTestId("capability-card")).toHaveTextContent("Added, switched and removed as one group");
    // Who published it is the repository's account, never a package's.
    expect(screen.getByTestId("capability-card")).not.toHaveTextContent(/publisher|published by/i);
  });

  it("one button adds the whole group, with the key typed once", () => {
    const { onConfirm } = show();
    expect(screen.getByTestId("capability-card-allow")).toBeDisabled();
    fireEvent.change(screen.getByTestId("capability-key-Authorization"), { target: { value: "typed" } });
    fireEvent.click(screen.getByTestId("capability-card-allow"));
    expect(onConfirm).toHaveBeenCalledWith("c1", { Authorization: "typed" }, []);
    expect(screen.getAllByTestId("capability-card-allow")).toHaveLength(1);
  });

  it("each connection's security, by its own lock; a remote and the skills say why they aren't checked", () => {
    show();
    const row = screen.getByTestId("capability-card-security");
    expect(row).toHaveTextContent("md-tools");
    expect(row).toHaveTextContent("No known vulnerabilities in the 38 packages in the lock.");
    expect(row).toHaveTextContent("Not checked: it runs on its own server");
    expect(row).toHaveTextContent("Skills aren't checked for known vulnerabilities");
  });
});

describe("a known vulnerability (board Risky)", () => {
  it("in one connection: Don't install is the default, installing anyway stays possible", () => {
    const hit = { ...local, vulns: checked({ count: 1, highest: "HIGH", own_highest: "HIGH", own: [adv("GHSA-aaaa-bbbb-cccc")] }) };
    const { onConfirm, onCancel } = show({ ...PLUGIN, keys: [], connections: [remote, hit] });
    expect(screen.getByTestId("capability-card-decline")).toHaveTextContent("Don't install");
    expect(screen.getByTestId("capability-card-allow")).toHaveTextContent("Install anyway");
    expect(screen.getByTestId("capability-card-security")).toHaveTextContent("GHSA-aaaa-bbbb-cccc");
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("capability-card-allow"));
    expect(onConfirm).toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("only in a dependency: the plain buttons stay", () => {
    const dep = { ...local, vulns: checked({ count: 1, highest: "LOW", deps_highest: "LOW",
      deps: [{ name: "x", alias: null, version: "1", more: 0, advisories: [adv("GHSA-1111-2222-3333")] }] }) };
    show({ ...PLUGIN, keys: [], connections: [dep] });
    expect(screen.getByTestId("capability-card-allow")).toHaveTextContent("Add and retry");
  });
});

describe("a refused plugin (board Refused)", () => {
  const refused = (code: string, detail = "") => {
    act(() => { useArslanStore.getState().handleFrame({ type: "capability_result", call_id: null, source_id: null,
      state: "refused", name: "auto-format", tools: 0, code, detail } as never); });
    const msgs = toUiMessages(useArslanStore.getState().items as never);
    render(<CapabilityResultLine result={msgs[msgs.length - 1].capabilityResult!} />);
    return screen.getByTestId("capability-result");
  };

  it("is one plain red line naming what isn't supported and that nothing was installed", () => {
    useArslanStore.setState(initialArslanState(), true);
    const line = refused("hooks", "hooks");
    expect(line).toHaveAttribute("data-state", "refused");
    expect(line).toHaveTextContent("Not added: auto-format needs hooks that run on their own. Nothing was installed.");
    expect(line.className).toContain("text-danger");
    expect(useArslanStore.getState().pendingCapabilities).toEqual([]);
  });

  it.each([
    ["cannot_pin", "bridge", "the connection bridge in auto-format can’t be locked to a version"],
    ["runs_from_source", "bridge", "the connection bridge in auto-format can’t be locked to a version"],
    ["add_by_hand", "tickets", "tickets isn’t on your one-click list"],
    ["no_such_code_yet", "x", "auto-format can’t be added (no_such_code_yet)"],
  ])("says which part and why (%s)", (code, detail, text) => {
    const line = refused(code, detail);
    expect(line).toHaveTextContent(text);
    expect(line).toHaveTextContent("Nothing was installed.");
  });
});

const row = (over: Partial<CapabilityRow>): CapabilityRow => ({ key: "x", section: "builtin", origin: "builtin",
  deletable: false, last_used: null, source_id: null, reach: null, state: "on", tools: [], switch: null, reason: null,
  fix: null, name: null, detail: null, ...over });
const part = (kind: "skill" | "connection", key: string, name: string, over = {}) => ({ kind, key, name, state: "on" as const,
  reason: null, detail: null, last_used: null, source_id: null, fix: null, ...over });
const KIT = row({ key: "plugin:p1", section: "plugins", origin: "installed", deletable: true, switch: "plugin",
  source_id: "p1", name: "notes-kit", detail: "Writes release notes", parts: [
    part("connection", "mcp:7", "tickets", { state: "setup", reason: "needs_sign_in", fix: "open_tab:mcps", source_id: "c7" }),
    part("connection", "mcp:8", "md-tools", { source_id: "c8" }),
    part("skill", "skill:notes", "notes"), part("skill", "skill:style", "style")] });
const STOPPED = row({ key: "plugin:p2", section: "plugins", origin: "installed", deletable: true, switch: "plugin",
  source_id: "p2", name: "deploy-kit", state: "setup", reason: "plugin_stopped", fix: "open_tab:mcps", detail: "render",
  parts: [part("connection", "mcp:9", "render", { state: "off", source_id: "c9" })] });
const OTHERS = [row({ key: "terminal", switch: "setting" }),
  row({ key: "skill:mine", section: "skills", origin: "authored", deletable: true, switch: "skill", name: "mine" })];

describe("Capabilities (board Group)", () => {
  it("has no Plugins group until a plugin is installed", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(OTHERS);
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-terminal");
    expect(screen.queryByTestId("cap-section-plugins")).toBeNull();
  });

  it("shows each plugin as one row, first, with one switch, one delete, and what's inside on request", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([...OTHERS, KIT]);
    const flip = vi.spyOn(capabilitiesApi, "switch").mockResolvedValue({ ...KIT, state: "off" });
    render(<CapabilitySwitches />);
    const group = await screen.findByTestId("cap-section-plugins");
    expect(screen.getAllByTestId(/^cap-section-/)[0]).toBe(group);
    expect(group).toHaveTextContent("Plugins");
    const kit = within(group).getByTestId("cap-plugin:p1");
    expect(within(kit).getAllByRole("switch")).toHaveLength(1);
    expect(within(kit).getAllByRole("button", { name: /Delete/ })).toHaveLength(1);
    expect(kit).toHaveTextContent("Writes release notes · You installed");
    expect(screen.queryByTestId("plugin-parts-plugin:p1")).toBeNull();
    fireEvent.click(within(kit).getByText("Show what's inside"));
    const parts = screen.getByTestId("plugin-parts-plugin:p1");
    expect(within(parts).getAllByTestId(/^plugin-part-(?!open)/).map(p => p.textContent)).toEqual([
      expect.stringContaining("tickets"), expect.stringContaining("md-tools"),
      expect.stringContaining("notes"), expect.stringContaining("style")]);
    expect(within(parts).queryAllByRole("switch", { hidden: true })).toHaveLength(0);     // no part switches alone
    expect(within(parts).queryAllByRole("button", { name: /Delete/ })).toHaveLength(0);
    expect(within(parts).getByTestId("plugin-part-mcp:7")).toHaveTextContent("Needs sign-in");
    fireEvent.click(within(kit).getByRole("switch"));
    expect(flip).toHaveBeenCalledWith("plugin:p1", false);
  });

  it("a stopped plugin says which connection changed; Check the change opens it, and it can go back on", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([...OTHERS, STOPPED]);
    const flip = vi.spyOn(capabilitiesApi, "switch").mockResolvedValue({ ...STOPPED, state: "on", reason: null });
    render(<CapabilitySwitches />);
    const stopped = await screen.findByTestId("cap-plugin:p2");
    expect(stopped).toHaveTextContent("Stopped");
    expect(stopped).toHaveTextContent("The connection render changed its tools, so the whole plugin is off until you check the change.");
    fireEvent.click(within(stopped).getByText("Check the change"));
    const sheet = await screen.findByTestId("cap-sheet");
    expect(within(sheet).getByTestId("plugin-parts-plugin:p2")).toHaveTextContent("render");
    fireEvent.click(within(sheet).getByTestId("plugin-switch-back"));
    await waitFor(() => expect(flip).toHaveBeenCalledWith("plugin:p2", true));
  });

  it("parts no longer show on their own in Skills or Connections", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([...OTHERS, KIT]);
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-section-plugins");
    expect(screen.queryByTestId("cap-mcp:7")).toBeNull();
    expect(screen.queryByTestId("cap-skill:notes")).toBeNull();
  });
});
