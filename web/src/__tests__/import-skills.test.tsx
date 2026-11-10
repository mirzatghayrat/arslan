// CAP8-2's web part: Claude Code's skills as rows on the Import sheet, with the sheet's own row parts. A skill comes in
// switched off and is switched on through CAP6a's card, so the sheet says that, and what it sends is the row it showed.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";

vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn().mockResolvedValue([]), listMcpTools: vi.fn().mockResolvedValue([]),
}));

import { capabilitiesApi } from "../api/capabilities";
import type { ImportResult, ImportRow, ImportScan, ImportSkillRow } from "../api/client.types";
import CapabilitySwitches from "../components/CapabilitySwitches";
import { capabilityListMessages } from "../locales/capabilityList";

const en = capabilityListMessages.en;
const skill = (over: Partial<ImportSkillRow> & { id: string; name: string }): ImportSkillRow => ({
  tool: "claude_code", kind: "skill", digest: `digest-of-${over.id}`, key: over.name, description: "Writes notes.",
  scripts: [], references: [], left: 0, scan: "clean", here: false, same_as: null, refused: null, refused_part: null,
  tick: true, ...over });
const SERVER: ImportRow = { id: "claude_code:md-tools", tool: "claude_code", name: "md-tools", digest: "digest-of-server",
  kind: "package", command: "npx", arguments: ["md-tools@1.0.0"], address: null, network: false, env: [], keys: 0, asks: [],
  on_there: true, tool_limits: false, here: false, same_as: null, refused: null, refused_part: null, tick: true };

const NOTES = skill({ id: "skill:skills/release-notes", name: "release-notes", scripts: ["fmt.py"], left: 2 });
const WARN = skill({ id: "skill:skills/careful", name: "careful", scan: "warn" });
const BLOCKED = skill({ id: "skill:skills/bad", name: "bad", refused: "blocked", refused_part: "download_and_run",
  scan: "blocked", tick: true });
const HERE = skill({ id: "skill:skills/old", name: "old", here: true, tick: false });
const COPY = skill({ id: "skill:skills/release-notes-copy", name: "release-notes-copy", key: "release-notes",
  same_as: NOTES.id, tick: false });

const scanOf = (skills: ImportSkillRow[], servers: ImportRow[] = []): ImportScan => ({
  tools: [{ tool: "claude_code", state: "read", count: servers.length }, { tool: "codex", state: "missing", count: 0 }],
  servers, skills });

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
const foot = () => screen.getByTestId("import-foot").textContent ?? "";

async function openSheet(skills: ImportSkillRow[], servers: ImportRow[] = []) {
  scanSpy.mockResolvedValue(scanOf(skills, servers));
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

describe("a skill row", () => {
  it("has the sheet's tick, name and tool, and says it comes in off until its card", async () => {
    await openSheet([NOTES]);
    const el = rowEl("release-notes");
    expect(tick("release-notes").checked).toBe(true);
    expect(el).toHaveTextContent("Claude Code");
    expect(within(el).getByTestId("import-skill")).toHaveTextContent(en.import_skill);
    expect(el).toHaveTextContent("fmt.py");
    expect(el).toHaveTextContent("2 other files in its folder stay behind.");
  });

  it("a scan finding is said, and the card is where it is read", async () => {
    await openSheet([WARN]);
    expect(rowEl("careful")).toHaveTextContent(en.import_skillWarn);
  });

  it("a blocked one can't be ticked, whatever the server's tick says, and names why", async () => {
    await openSheet([BLOCKED, NOTES]);
    expect(tick("bad").disabled).toBe(true);
    expect(tick("bad").checked).toBe(false);
    expect(rowEl("bad")).toHaveTextContent(en.import_refused_blocked);
    expect(rowEl("bad")).toHaveTextContent("download_and_run");
    fireEvent.click(addButton());
    expect(addSpy.mock.calls[0][1]?.map(s => s.id)).toEqual([NOTES.id]);
  });

  it("one already here sits in the here line, and a second copy starts unticked and names the first", async () => {
    await openSheet([NOTES, HERE, COPY]);
    expect(screen.getByTestId("import-here")).toHaveTextContent("old");
    expect(screen.queryAllByTestId("import-row").map(el => el.dataset.name)).toEqual(["release-notes", "release-notes-copy"]);
    expect(tick("release-notes-copy").checked).toBe(false);
    expect(rowEl("release-notes-copy").textContent).toMatch(/Same skill as .?release-notes.?, so one is enough\./);
  });

  it("with no servers but a skill, the sheet isn't empty", async () => {
    await openSheet([NOTES]);
    expect(screen.queryByTestId("import-nothing")).toBeNull();
  });
});

describe("what it sends", () => {
  it("a ticked skill sends its id and digest as a skill, beside the servers; an unticked one sends nothing", async () => {
    await openSheet([NOTES, WARN], [SERVER]);
    fireEvent.click(tick("careful"));
    expect(addButton()).toHaveTextContent("Add 2");
    fireEvent.click(addButton());
    expect(addSpy).toHaveBeenCalledTimes(1);
    expect(addSpy.mock.calls[0][0].map(s => s.id)).toEqual([SERVER.id]);
    expect(addSpy.mock.calls[0][1]).toEqual([{ id: NOTES.id, digest: NOTES.digest, keys: {} }]);
  });

  it("the copied line says it's off until its card in Capabilities", async () => {
    await openSheet([NOTES]);
    const results: ImportResult[] = [{ id: NOTES.id, state: "added", key: "release-notes" }];
    addSpy.mockResolvedValue({ results });
    fireEvent.click(addButton());
    const line = await screen.findByTestId("import-result-added");
    expect(line.textContent).toMatch(/^Copied .?release-notes.? in, switched off\. Switch it on in Capabilities to read its card first\.$/);
    expect(line.className).not.toContain("text-warning");
  });
});

describe("the footer", () => {
  it("with only skills ticked says the card comes first, and not that each one is tested", async () => {
    await openSheet([NOTES], [SERVER]);
    fireEvent.click(tick("md-tools"));
    expect(foot()).toContain(en.import_skillFoot);
    expect(foot()).not.toContain(en.import_testedFoot);
    fireEvent.click(tick("md-tools"));
    expect(foot()).toContain(en.import_testedFoot);
    fireEvent.click(tick("release-notes"));
    expect(foot()).not.toContain(en.import_skillFoot);
  });
});

describe("the words", () => {
  it.each(["zh", "ja", "es", "de", "fr"] as const)("%s has the skill keys in its own words", (language) => {
    const there = capabilityListMessages[language] as Record<string, string>;
    for (const key of ["import_skill", "import_skillFoot", "import_result_copied", "import_sameSkill", "import_refused_blocked"]) {
      expect(there[key], key).toBeTruthy();
      expect(there[key], key).not.toBe((en as Record<string, string>)[key]);
    }
  });
});
