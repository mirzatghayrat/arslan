// CAP8-2's plugin follow-up (board 7, "Import sheet with plugins"): Claude Code's plugins as a group on the Import sheet.
// A plugin starts unticked. With one ticked, Add adds the other picks first, then shows that plugin's CAP7b card, and
// only "Add plugin" on that card sends it back with the card's digest. One that can't come in is one red line.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";

vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn().mockResolvedValue([]), listMcpTools: vi.fn().mockResolvedValue([]),
}));

import { capabilitiesApi } from "../api/capabilities";
import type { ImportPluginCard, ImportPluginRow, ImportResult, ImportScan, ImportSkillRow } from "../api/client.types";
import CapabilitySwitches from "../components/CapabilitySwitches";
import { capabilityListMessages } from "../locales/capabilityList";

const en = capabilityListMessages.en;
const plugin = (over: Partial<ImportPluginRow> & { id: string; name: string }): ImportPluginRow => ({
  tool: "claude_code", kind: "plugin", digest: `digest-of-${over.id}`, skills: ["changelog-style"], connections: ["linear"],
  hooks: ["SessionStart"], from: "acme", here: false, same_as: null, refused: null, refused_part: null, tick: true, ...over });
const KIT = plugin({ id: "plugin:plugins/acme/release-kit/1.0.0", name: "release-kit" });
const GUARD = plugin({ id: "plugin:plugins/acme/deploy-guard/1.0.0", name: "deploy-guard", refused: "hooks",
  refused_part: "PreToolUse" });
const NOTION = plugin({ id: "plugin:plugins/acme/notion/1.0.0", name: "notion", here: true });
const SKILL: ImportSkillRow = { id: "skill:skills/pr-review", tool: "claude_code", kind: "skill", name: "pr-review",
  digest: "digest-of-skill", key: "pr-review", description: "Reviews.", scripts: [], references: [], left: 0, scan: "clean",
  here: false, same_as: null, refused: null, refused_part: null, tick: true };
const CARD: ImportPluginCard = {
  name: "release-kit", summary: "Writes release notes and files them in Linear", from: "acme", hooks: ["SessionStart"],
  commit: "0".repeat(40), license: { spdx: null, read_from: null }, folders: [], keys: [], publisher: null,
  skills: [{ key: "changelog-style", name: "changelog-style", summary: "Style.", scripts: [], references: [] }],
  connections: [{ name: "linear", runtime: "remote", package: null, version: null, remote_host: "https://mcp.linear.app/mcp",
    network: true, arguments: [], env: {}, headers: {}, keys: [], vulns: { state: "skipped", why: "remote" } }],
};

const scanOf = (plugins: ImportPluginRow[], skills: ImportSkillRow[] = []): ImportScan => ({
  tools: [{ tool: "claude_code", state: "read", count: 0 }, { tool: "codex", state: "missing", count: 0 }],
  servers: [], skills, plugins });

const scanSpy = vi.spyOn(capabilitiesApi, "importScan");
const addSpy = vi.spyOn(capabilitiesApi, "importAdd");
const listSpy = vi.spyOn(capabilitiesApi, "list");

function rowEl(name: string) {
  const found = screen.getAllByTestId("import-row").find(el => el.dataset.name === name);
  if (!found) throw new Error(`no row ${name}`);
  return found;
}
const tick = (name: string) => within(rowEl(name)).getByRole<HTMLInputElement>("checkbox");
const addButton = () => screen.getByTestId<HTMLButtonElement>("import-add");

async function openSheet(plugins: ImportPluginRow[], skills: ImportSkillRow[] = []) {
  scanSpy.mockResolvedValue(scanOf(plugins, skills));
  render(<CapabilitySwitches />);
  await screen.findByTestId("cap-section-connections");
  fireEvent.click(screen.getByTestId("cap-add-import"));
  await screen.findByTestId("import-add");
}

beforeEach(() => {
  scanSpy.mockReset(); addSpy.mockReset(); listSpy.mockReset();
  listSpy.mockResolvedValue([]);
});
afterEach(() => { cleanup(); void i18n.changeLanguage("en"); });

describe("the Plugins group", () => {
  it("has its own heading, and a plugin starts unticked whatever the server's tick says", async () => {
    await openSheet([KIT], [SKILL]);
    expect(screen.getByTestId("import-group-plugins")).toHaveTextContent(en.section_plugins);
    expect(tick("release-kit").checked).toBe(false);
    expect(tick("pr-review").checked).toBe(true);
    expect(rowEl("release-kit")).toHaveTextContent("Claude Code");
    expect(within(rowEl("release-kit")).getByTestId("import-plugin").textContent)
      .toBe("Holds 1 skill, 1 connection, 1 hook that won't run. You see its card before it is added.");
  });

  it("one that can't come in is one red line naming why, with no tick", async () => {
    await openSheet([GUARD, KIT, NOTION]);
    expect(screen.queryAllByTestId("import-row").map(el => el.dataset.name)).toEqual(["release-kit"]);
    const line = screen.getByTestId("import-plugin-refused");
    expect(line.textContent).toMatch(/^Can't be imported: .?deploy-guard.?\. It has a hook that can block or stop actions \(PreToolUse\)\. Arslan doesn't run hooks, so that protection would be missing\.$/);
    expect(line.className).toContain("text-danger-strong");
    expect(within(line).queryByRole("checkbox")).toBeNull();
    expect(screen.getByTestId("import-here")).toHaveTextContent("notion");
  });

  it("ticking it names the card in the button", async () => {
    await openSheet([KIT], [SKILL]);
    expect(addButton()).toHaveTextContent("Add 1");
    fireEvent.click(tick("release-kit"));
    expect(addButton()).toHaveTextContent("Add 2, then look at the plugin");
  });
});

describe("Add, then the card", () => {
  it("adds the other picks first, then shows the plugin's card, and only Add plugin sends its digest", async () => {
    await openSheet([KIT], [SKILL]);
    fireEvent.click(tick("release-kit"));
    const first: ImportResult[] = [{ id: SKILL.id, state: "added", key: "pr-review" },
      { id: KIT.id, state: "card", card: CARD, card_digest: "card-digest" }];
    addSpy.mockResolvedValueOnce({ results: first });
    fireEvent.click(addButton());
    const card = await screen.findByTestId("import-plugin-card");
    expect(addSpy).toHaveBeenCalledTimes(1);
    expect(addSpy.mock.calls[0][1]).toEqual([{ id: SKILL.id, digest: SKILL.digest, keys: {} }]);
    expect(addSpy.mock.calls[0][2]).toEqual([{ id: KIT.id, digest: KIT.digest, keys: {} }]);     // no card digest yet
    expect(card.textContent).toMatch(/Add the plugin .?release-kit.? from Claude Code/);
    expect(within(card).getByTestId("capability-card-source").textContent).toMatch(/Installed in Claude Code from .?acme.?$/);
    expect(within(card).getByTestId("import-card-hooks").textContent)
      .toBe("1 hook, won't run: SessionStart, when a conversation starts.Arslan doesn't run hooks. Anything in this plugin that depends on them may not work.");
    expect(within(card).getAllByTestId("plugin-part").map(el => el.dataset.kind)).toEqual(["skill", "connection"]);
    expect(within(card).getByTestId("capability-card-security")).toBeTruthy();
    expect(screen.getByTestId("import-card-skip")).toHaveTextContent("Skip this one");
    addSpy.mockResolvedValueOnce({ results: [{ id: KIT.id, state: "on", tools: 2 }] });
    fireEvent.click(screen.getByTestId("import-card-add"));
    await screen.findByTestId("import-results");
    expect(addSpy).toHaveBeenCalledTimes(2);
    expect(addSpy.mock.calls[1]).toEqual([[], [], [{ id: KIT.id, digest: KIT.digest, keys: {}, card: "card-digest" }]]);
    expect(screen.getByTestId("import-result-added")).toBeTruthy();
    expect(screen.getByTestId("import-result-on")).toBeTruthy();
  });

  it("Skip this one sends nothing more, and says it was skipped", async () => {
    await openSheet([KIT]);
    fireEvent.click(tick("release-kit"));
    addSpy.mockResolvedValueOnce({ results: [{ id: KIT.id, state: "card", card: CARD, card_digest: "card-digest" }] });
    fireEvent.click(addButton());
    await screen.findByTestId("import-plugin-card");
    fireEvent.click(screen.getByTestId("import-card-skip"));
    await screen.findByTestId("import-results");
    await waitFor(() => expect(screen.getByTestId("import-result-skipped")).toBeTruthy());
    expect(addSpy).toHaveBeenCalledTimes(1);
  });

  it("with no hooks, the card has no Hooks row", async () => {
    await openSheet([plugin({ id: KIT.id, name: "release-kit", hooks: [] })]);
    fireEvent.click(tick("release-kit"));
    addSpy.mockResolvedValueOnce({ results: [{ id: KIT.id, state: "card", card: { ...CARD, hooks: [] }, card_digest: "d" }] });
    fireEvent.click(addButton());
    await screen.findByTestId("import-plugin-card");
    expect(screen.queryByTestId("import-card-hooks")).toBeNull();
  });
});

describe("the words", () => {
  it.each(["zh", "ja", "es", "de", "fr"] as const)("%s has the plugin keys in its own words", (language) => {
    const there = capabilityListMessages[language] as Record<string, string>;
    const keys = Object.keys(en).filter(key => key.startsWith("import_card") || key.startsWith("import_plugin")
      || key.startsWith("hookWhen_") || key.startsWith("import_refused_hooks") || key === "plugin_hooks");
    expect(keys.length).toBeGreaterThan(20);
    for (const key of keys) {
      expect(there[key], key).toBeTruthy();
      expect(there[key], key).not.toBe((en as Record<string, string>)[key]);
    }
  });
});
