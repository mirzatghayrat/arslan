/** 0.1.55 §14 / v0.1.64 CAP3a: Capabilities as one list: built in, skills, connections; on / off / one step away
 *  / can't, with the reason; where each came from and when it was last used; delete only what is not built in. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) =>
    o && "count" in o ? `${key}:${o.count}` : o && "detail" in o ? `${key}:${o.detail}`
      : o && "number" in o ? `${key}:${o.number}` : o && "query" in o ? `${key}:${o.query}` : key }),
}));
vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn().mockResolvedValue([]), listMcpTools: vi.fn().mockResolvedValue([]),
}));

import CapabilitySwitches, { isolate, usedLabel } from "../components/CapabilitySwitches";
import { capabilitiesApi, type CapabilityRow } from "../api/capabilities";
import { ApiError } from "../api/client";
import { professionalMethodsApi } from "../api/professionalMethods";
import { ConfirmHost } from "../components/kit";
import { OPEN_SECTION_EVENT } from "../lib/sections";
import { capabilityListMessages } from "../locales/capabilityList";

const row = (over: Partial<CapabilityRow>): CapabilityRow => ({ key: "x", section: "builtin", origin: "builtin",
  deletable: false, last_used: null, source_id: null, reach: null, state: "on", tools: [], switch: null, reason: null, fix: null,
  name: null, detail: null, ...over });

const SKILL = { section: "skills", origin: "installed", deletable: true, switch: "skill" } as const;
const ROWS: CapabilityRow[] = [
  row({ key: "terminal", state: "on", switch: "setting", last_used: new Date().toISOString() }),
  row({ key: "files", state: "off", switch: "setting", detail: "own_folder_only" }),
  row({ key: "hands", state: "setup", reason: "hands_missing", fix: "open_settings:abilities" }),
  row({ key: "web", state: "setup", reason: "no-key", fix: "open_settings:connections" }),
  row({ key: "mcp:2", section: "connections", origin: "manual", deletable: true, state: "na", reason: "runtime_missing",
        detail: "npx", name: "Files", reach: "npx -y @playwright/mcp@latest" }),
  row({ key: "mcp:3", section: "connections", origin: "installed", deletable: true, source_id: "m3", state: "setup",
        reason: "mcp_error", fix: "open_tab:mcps", name: "Broken", switch: "mcp", detail: "401" }),
  ...Array.from({ length: 8 }, (_, i) => row({ key: `skill:s${i}`, ...SKILL, name: `Skill ${i}`, detail: `does ${i}` })),
  row({ key: "skill:mine", section: "skills", origin: "authored", deletable: true, switch: "skill", name: "Mine" }),
  row({ key: "skill:gh-acme", section: "skills", origin: "installed", deletable: true, switch: "skill", name: "Acme" }),
  row({ key: "method:research", section: "skills", revision: 2, name: "Research, my way" }),
  row({ key: "method:product-design", section: "skills", revision: 1 }),
];

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("capability list", () => {
  it("draws each state its own way: a switch, a one-step button, or the reason", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    expect(await screen.findByTestId("cap-switch-terminal")).toBeChecked();
    expect(screen.getByTestId("cap-switch-files")).not.toBeChecked();
    expect(screen.getByTestId("cap-files")).toHaveTextContent("capabilityList.detail_own_folder_only");
    expect(screen.getByTestId("cap-fix-hands")).toHaveTextContent("capabilityList.reason_hands_missing");
    const na = screen.getByTestId("cap-mcp:2");
    expect(within(na).queryByRole("switch")).toBeNull();
    expect(na).toHaveTextContent("capabilityList.reason_runtime_missing:npx");
    // An errored connection shows why, and its fix, not a switch that would do nothing.
    expect(within(screen.getByTestId("cap-mcp:3")).queryByRole("switch")).toBeNull();
    expect(screen.getByTestId("cap-mcp:3")).toHaveTextContent("401");
  });

  it("three sections in order, each row with where it came from and when it was last used", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-terminal");
    expect(screen.getAllByTestId(/^cap-section-/).map(el => el.dataset.testid))
      .toEqual(["cap-section-builtin", "cap-section-skills", "cap-section-connections"]);
    expect(within(screen.getByTestId("cap-section-connections")).getByTestId("cap-mcp:3")).toBeInTheDocument();
    expect(screen.getByTestId("cap-terminal")).toHaveTextContent("capabilityList.origin_builtin · capabilityList.usedToday");
    expect(screen.getByTestId("cap-skill:s1")).toHaveTextContent("does 1 · capabilityList.origin_installed · capabilityList.usedNever");
    expect(screen.getByTestId("cap-mcp:2")).toHaveTextContent("capabilityList.origin_manual");
    // The professional methods sit with the skills (after the first six here): the stored name once revised,
    // else named by key.
    fireEvent.click(screen.getByTestId("cap-more-skills"));
    expect(screen.getByTestId("cap-method:research")).toHaveTextContent("Research, my way");
    expect(screen.getByTestId("cap-method:product-design")).toHaveTextContent("methods.product-design");
    expect(screen.getByTestId("cap-method:research")).toHaveTextContent("capabilityList.methodWhat");
    // "MCP" is not on the list itself, only in a connection's details.
    expect(screen.getByTestId("cap-section-connections")).not.toHaveTextContent("MCP");
  });

  it("only rows that are not built in have a delete button", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-terminal");
    for (const key of ["terminal", "files", "hands", "method:research"]) expect(screen.queryByTestId(`cap-delete-${key}`)).toBeNull();
    for (const key of ["skill:s0", "mcp:2", "mcp:3"]) expect(screen.getByTestId(`cap-delete-${key}`)).toBeInTheDocument();
  });

  it("delete asks first, then deletes, says so and reloads; no deletes nothing", async () => {
    const list = vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    const del = vi.spyOn(capabilitiesApi, "deleteRow").mockResolvedValue({ ok: true });
    render(<><CapabilitySwitches /><ConfirmHost /></>);
    fireEvent.click(await screen.findByTestId("cap-delete-skill:s0"));
    const ask = await screen.findByTestId("confirm-sheet");
    expect(ask).toHaveTextContent("capabilityList.deleteTitle");
    expect(ask).toHaveTextContent("capabilityList.deleteBodyInstalledSkill");
    fireEvent.click(within(ask).getByTestId("confirm-cancel"));
    await waitFor(() => expect(screen.queryByTestId("confirm-sheet")).toBeNull());
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("cap-delete-skill:s0"));
    fireEvent.click(within(await screen.findByTestId("confirm-sheet")).getByRole("button", { name: /^capabilityList\.delete/ }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("skill:s0"));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });

  it("a failed delete says so", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    vi.spyOn(capabilitiesApi, "deleteRow").mockRejectedValue(new Error("409"));
    render(<><CapabilitySwitches /><ConfirmHost /></>);
    fireEvent.click(await screen.findByTestId("cap-delete-mcp:2"));
    expect(await screen.findByTestId("confirm-sheet")).toHaveTextContent("capabilityList.deleteBodyManual");
    fireEvent.click(within(screen.getByTestId("confirm-sheet")).getByRole("button", { name: /^capabilityList\.delete/ }));
    expect(await screen.findByText("capabilityList.deleteFailed")).toBeInTheDocument();
  });

  it("the delete question says what is lost, by what the row is", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<><CapabilitySwitches /><ConfirmHost /></>);
    await screen.findByTestId("cap-terminal");
    fireEvent.click(screen.getByTestId("cap-more-skills"));
    for (const [key, body] of [["skill:mine", "deleteBodyAuthored"], ["skill:s0", "deleteBodyInstalledSkill"],
      ["skill:gh-acme", "deleteBodyAuthored"],               // Discover's: no link to add it again from
      ["mcp:2", "deleteBodyManual"], ["mcp:3", "deleteBodyInstalledConnection"]]) {
      fireEvent.click(screen.getByTestId(`cap-delete-${key}`));
      expect(await screen.findByTestId("confirm-sheet")).toHaveTextContent(`capabilityList.${body}`);
      fireEvent.click(screen.getByTestId("confirm-cancel"));
      await waitFor(() => expect(screen.queryByTestId("confirm-sheet")).toBeNull());
    }
    // #500 review: none of them says "switched off" or promises a way back that is not there.
    for (const body of ["deleteBodyAuthored", "deleteBodyInstalledSkill", "deleteBodyManual", "deleteBodyInstalledConnection"]) {
      expect(capabilityListMessages.en[body as keyof typeof capabilityListMessages.en]).not.toMatch(/switched off/i);
    }
    expect(capabilityListMessages.en.deleteBodyAuthored).toMatch(/for good/);
  });

  it("a delete the server answers 404 or 409 reads the list again and says which", async () => {
    const list = vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    vi.spyOn(capabilitiesApi, "deleteRow").mockRejectedValueOnce(new ApiError("gone", 404))
      .mockRejectedValueOnce(new ApiError("refused", 409));
    render(<><CapabilitySwitches /><ConfirmHost /></>);
    fireEvent.click(await screen.findByTestId("cap-delete-skill:s0"));
    fireEvent.click(within(await screen.findByTestId("confirm-sheet")).getByRole("button", { name: /^capabilityList\.delete/ }));
    expect(await screen.findByText("capabilityList.deleteGone")).toBeInTheDocument();
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByTestId("cap-delete-skill:s1"));
    fireEvent.click(within(await screen.findByTestId("confirm-sheet")).getByRole("button", { name: /^capabilityList\.delete/ }));
    expect(await screen.findByText("capabilityList.deleteRefused")).toBeInTheDocument();
    await waitFor(() => expect(list).toHaveBeenCalledTimes(3));
  });

  it("a refused delete from the details sheet is said inside the sheet", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    vi.spyOn(capabilitiesApi, "deleteRow").mockRejectedValue(new ApiError("refused", 409));
    render(<><CapabilitySwitches /><ConfirmHost /></>);
    fireEvent.click(await screen.findByTestId("cap-open-mcp:2"));
    fireEvent.click(within(await screen.findByTestId("cap-sheet")).getByTestId("cap-sheet-delete"));
    fireEvent.click(within(await screen.findByTestId("confirm-sheet")).getByRole("button", { name: /^capabilityList\.delete/ }));
    expect(await within(screen.getByTestId("cap-sheet")).findByTestId("cap-sheet-error"))
      .toHaveTextContent("capabilityList.deleteRefused");
  });

  it("a connection is found by how it is reached, not only by its label", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-terminal");
    fireEvent.change(screen.getByTestId("cap-search"), { target: { value: "@playwright" } });
    expect(screen.getByTestId("cap-mcp:2")).toBeInTheDocument();
    expect(screen.queryByTestId("cap-mcp:3")).toBeNull();
  });

  it("an isolated name cannot close its isolate early or reorder what follows", () => {
    expect(isolate("Notes\u2069\u202E evil\u200F")).toBe("\u2068Notes evil\u2069");
    expect(isolate("plain")).toBe("\u2068plain\u2069");
  });

  it("outside names are isolated, in the row and inside Arslan's own sentences", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<><CapabilitySwitches /><ConfirmHost /></>);
    const skill = await screen.findByTestId("cap-skill:s1");
    expect([...skill.querySelectorAll("bdi")].map(el => el.textContent)).toEqual(["Skill 1", "does 1"]);
    fireEvent.click(screen.getByTestId("cap-delete-skill:s1"));
    // The title's {{name}} is the isolated name (the test's t() leaves the key; the sheet title is checked by key).
    expect(await screen.findByTestId("confirm-sheet")).toHaveTextContent("capabilityList.deleteTitle");
  });

  it("a row opens its details: what, where from, last used; a built-in says it is only switched", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-open-terminal"));
    const sheet = await screen.findByTestId("cap-sheet");
    expect(sheet).toHaveTextContent("capabilityList.kind_builtin");
    expect(within(sheet).getByTestId("cap-sheet-what")).toHaveTextContent("capabilityList.terminal_what");
    expect(within(sheet).getByTestId("cap-sheet-origin")).toHaveTextContent("capabilityList.origin_builtin");
    expect(within(sheet).getByTestId("cap-sheet-used")).toHaveTextContent("capabilityList.usedToday");
    expect(within(sheet).getByTestId("cap-sheet-builtin")).toBeInTheDocument();
    expect(within(sheet).queryByTestId("cap-sheet-delete")).toBeNull();
  });

  it("a connection's details name it as an MCP service, open its dossier, and can delete it", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    const source = vi.spyOn(capabilitiesApi, "source").mockRejectedValue(new Error("offline"));
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-open-mcp:3"));
    const sheet = await screen.findByTestId("cap-sheet");
    expect(sheet).toHaveTextContent("capabilityList.kind_mcp");
    expect(within(sheet).getByTestId("cap-sheet-delete")).toBeInTheDocument();
    fireEvent.click(within(sheet).getByTestId("cap-sheet-dossier"));
    await waitFor(() => expect(source).toHaveBeenCalledWith("m3"));
  });

  it("a method's details show its version and open its editor", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    vi.spyOn(professionalMethodsApi, "list").mockResolvedValue([
      { key: "research", revision: 2, name: "Research, my way", instructions: "Cite every claim." }]);
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-more-skills"));
    fireEvent.click(screen.getByTestId("cap-open-method:research"));
    const sheet = await screen.findByTestId("cap-sheet");
    expect(within(sheet).getByTestId("cap-sheet-version")).toHaveTextContent("capabilityList.versionNumber:2");
    expect(within(sheet).queryByTestId("cap-sheet-delete")).toBeNull();
    fireEvent.click(within(sheet).getByTestId("cap-sheet-edit"));
    expect(await screen.findByDisplayValue("Cite every claim.")).toBeInTheDocument();
  });

  it("a switch writes through the API and shows what the server says now", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    const put = vi.spyOn(capabilitiesApi, "switch").mockResolvedValue(row({ key: "files", state: "on", switch: "setting" }));
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-switch-files"));
    await waitFor(() => expect(put).toHaveBeenCalledWith("files", true));
    await waitFor(() => expect(screen.getByTestId("cap-switch-files")).toBeChecked());
    expect(screen.getByTestId("cap-files")).toHaveAttribute("data-state", "on");
  });

  it("a failed switch says so and leaves the row as it was", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    vi.spyOn(capabilitiesApi, "switch").mockRejectedValue(new Error("offline"));
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-switch-terminal"));
    expect(await screen.findByText("capabilityList.failed")).toBeInTheDocument();
    expect(screen.getByTestId("cap-terminal")).toHaveAttribute("data-state", "on");
  });

  it("one step away opens the place that fixes it: Settings, or the connection's details", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    const seen: unknown[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(OPEN_SECTION_EVENT, on);
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-fix-web"));
    window.removeEventListener(OPEN_SECTION_EVENT, on);
    expect(seen).toEqual([{ section: "settings", sub: "connections" }]);
    fireEvent.click(screen.getByTestId("cap-fix-mcp:3"));
    expect(await screen.findByTestId("cap-sheet")).toHaveTextContent("Broken");
  });

  it("filters: on, can turn on (off or one step away), all", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-terminal");
    expect(screen.getByTestId("cap-filter-on")).toHaveTextContent("capabilityList.filterOn:13");
    expect(screen.getByTestId("cap-filter-canTurnOn")).toHaveTextContent("capabilityList.filterCanTurnOn:4");
    fireEvent.click(screen.getByTestId("cap-filter-canTurnOn"));
    expect(screen.queryByTestId("cap-terminal")).toBeNull();
    expect(screen.queryByTestId("cap-mcp:2")).toBeNull();          // can't is not "can turn on"
    expect(screen.getByTestId("cap-files")).toBeInTheDocument();
    expect(screen.getByTestId("cap-hands")).toBeInTheDocument();
  });

  it("search narrows every section, shows all it found, and says when nothing matches", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-terminal");
    const box = screen.getByTestId("cap-search");
    fireEvent.change(box, { target: { value: "skill" } });
    expect(screen.queryByTestId("cap-terminal")).toBeNull();
    expect(within(screen.getByTestId("cap-section-skills")).getAllByRole("switch")).toHaveLength(10);   // not folded
    fireEvent.change(box, { target: { value: "nothing like this" } });
    expect(screen.getByTestId("cap-no-match")).toHaveTextContent("capabilityList.noMatch:nothing like this");
  });

  it("a long section opens with its first six", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    const skills = await screen.findByTestId("cap-section-skills");
    expect(within(skills).getAllByTestId(/^cap-open-/)).toHaveLength(6);
    fireEvent.click(screen.getByTestId("cap-more-skills"));
    expect(within(skills).getAllByTestId(/^cap-open-/)).toHaveLength(12);
  });

  it("adds by hand from the connections header and pastes a link from the side", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue(ROWS);
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-add-manual"));
    const manual = await screen.findByTestId("cap-manual-sheet");
    expect(manual).toHaveTextContent("capabilityList.addByHandHint");
    expect(within(manual).getByRole("button", { name: /connectionsUI.addServer/ })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("cap-manual-sheet")).toBeNull());
    fireEvent.click(screen.getByTestId("cap-add-link"));
    expect(await screen.findByTestId("cap-link-sheet")).toHaveTextContent("capabilityList.addLink");
    // Saying what you need and writing a method happen in a conversation: nothing to click.
    expect(screen.getByTestId("cap-add-say").tagName).not.toBe("BUTTON");
    expect(screen.getByTestId("cap-add-method").tagName).not.toBe("BUTTON");
  });

  it("last used reads as today, yesterday, days ago, a date, or not yet", () => {
    const t = (key: string, o?: Record<string, unknown>) => (o ? `${key}:${Object.values(o)[0]}` : key);
    const now = new Date(2026, 9, 29, 15).getTime();
    expect(usedLabel(t, null, "en", now)).toBe("capabilityList.usedNever");
    expect(usedLabel(t, new Date(2026, 9, 29, 1).toISOString(), "en", now)).toBe("capabilityList.usedToday");
    expect(usedLabel(t, new Date(2026, 9, 28, 23).toISOString(), "en", now)).toBe("capabilityList.usedYesterday");
    expect(usedLabel(t, new Date(2026, 9, 24, 12).toISOString(), "en", now)).toBe("capabilityList.usedDaysAgo:5");
    expect(usedLabel(t, new Date(2026, 7, 1, 12).toISOString(), "en", now)).toMatch(/^capabilityList\.usedOn:/);
  });

  it("strings exist in six languages with the same placeholders", () => {
    const keys = Object.keys(capabilityListMessages.en).sort();
    for (const messages of Object.values(capabilityListMessages)) {
      expect(Object.keys(messages).sort()).toEqual(keys);
      for (const key of keys) {
        const text = messages[key as keyof typeof messages];
        expect(text.trim()).not.toBe("");
        expect(text.match(/\{\{[^}]+\}\}/g) ?? []).toEqual(capabilityListMessages.en[key as keyof typeof messages].match(/\{\{[^}]+\}\}/g) ?? []);
      }
    }
    // Every built-in row the server can send has a name and a line; every section and origin a label.
    for (const key of ["files", "terminal", "browser", "shortcuts", "hands", "web", "charts", "schedule", "lan", "ssh"]) {
      expect(capabilityListMessages.en).toHaveProperty(`${key}_name`);
      expect(capabilityListMessages.en).toHaveProperty(`${key}_what`);
    }
    for (const key of ["section_builtin", "section_skills", "section_connections", "origin_builtin", "origin_installed",
      "origin_authored", "origin_manual", "kind_builtin", "kind_skill", "kind_mcp"]) expect(capabilityListMessages.en).toHaveProperty(key);
    // "MCP" only in the connection's details tag and the hand-entry hint.
    for (const [key, text] of Object.entries(capabilityListMessages.en)) {
      if (!["kind_mcp", "addByHandHint"].includes(key)) expect(text).not.toMatch(/\bMCP\b/);
    }
  });
});
