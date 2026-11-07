// CAP8-1's web half: the sheet that brings in connections from Claude Code and Codex. It is the consent surface for a
// security-relevant import, so these read what the row says against what the POST sends. All names are invented.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";

vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn().mockResolvedValue([]), listMcpTools: vi.fn().mockResolvedValue([]),
}));

import { capabilitiesApi } from "../api/capabilities";
import type { ImportResult, ImportRow, ImportScan } from "../api/client.types";
import CapabilitySwitches from "../components/CapabilitySwitches";
import { capabilityListMessages } from "../locales/capabilityList";

const row = (over: Partial<ImportRow> & { id: string; name: string }): ImportRow => ({
  tool: "claude_code", digest: `digest-of-${over.id}`, kind: "package", command: "npx", arguments: ["-y", `${over.name}@1.0.0`],
  address: null, network: false, env: [], keys: 0, asks: [], on_there: true, tool_limits: false, here: false, same_as: null,
  refused: null, refused_part: null, tick: true, ...over });

const PACKAGE = row({ id: "claude_code:md-tools", name: "md-tools" });
const KEYED = row({ id: "codex:notes", tool: "codex", name: "notes", command: "uvx", arguments: ["notes-mcp==0.9.1"], network: true,
  keys: 1, env: ["NOTES_KEY"] });
const REMOTE = row({ id: "codex:tracker", tool: "codex", name: "tracker", kind: "remote", command: null, arguments: [],
  address: "https://mcp.tracker.example", network: true });
const PROGRAM = row({ id: "codex:my-server", tool: "codex", name: "my-server", kind: "program", command: "/opt/tools/run.sh",
  arguments: ["--port", "9000", "two words"], network: true, env: ["FOO_TOKEN", "PYTHONPATH"], keys: 1, tick: false });
const ASKING = row({ id: "claude_code:asking", name: "asking", env: ["API_KEY", "OTHER"], asks: ["API_KEY", "OTHER"], network: true });

const scan = (servers: ImportRow[], tools: ImportScan["tools"] = [
  { tool: "claude_code", state: "read", count: servers.length }, { tool: "codex", state: "read", count: 0 }]): ImportScan => ({ tools, servers });

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

async function openSheet(servers: ImportRow[], tools?: ImportScan["tools"]) {
  scanSpy.mockResolvedValue(scan(servers, tools));
  const view = render(<CapabilitySwitches />);
  await screen.findByTestId("cap-section-connections");
  fireEvent.click(screen.getByTestId("cap-add-import"));
  await screen.findByTestId("import-add");
  return view;
}

async function addAndGetResults(results: ImportResult[]) {
  addSpy.mockResolvedValue({ results });
  fireEvent.click(addButton());
  await screen.findByTestId("import-done");
}

beforeEach(() => {
  scanSpy.mockReset();
  addSpy.mockReset();
  listSpy.mockReset();
  listSpy.mockResolvedValue([]);
});
afterEach(() => { cleanup(); void i18n.changeLanguage("en"); });

describe("opening the sheet", () => {
  it("scans on the Import click and not when the page loads", async () => {
    scanSpy.mockResolvedValue(scan([PACKAGE]));
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-section-connections");
    expect(scanSpy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("cap-add-import"));
    await screen.findByTestId("import-add");
    expect(scanSpy).toHaveBeenCalledTimes(1);
    expect(addSpy).not.toHaveBeenCalled();
  });

  it("a scan that fails says so and offers another", async () => {
    scanSpy.mockRejectedValueOnce(new Error("offline"));
    render(<CapabilitySwitches />);
    await screen.findByTestId("cap-section-connections");
    fireEvent.click(screen.getByTestId("cap-add-import"));
    expect(await screen.findByTestId("import-scan-failed")).toHaveTextContent(capabilityListMessages.en.import_scanFailed);
    scanSpy.mockResolvedValueOnce(scan([PACKAGE]));
    fireEvent.click(screen.getByTestId("import-rescan"));
    await screen.findByTestId("import-add");
    expect(rowEl("md-tools")).toBeInTheDocument();
  });

  it("names a file it could not read, and says when there is nothing", async () => {
    await openSheet([], [{ tool: "claude_code", state: "missing", count: 0 }, { tool: "codex", state: "malformed", count: 0 }]);
    const lines = screen.getAllByTestId("import-malformed");
    expect(lines).toHaveLength(1);
    expect(lines[0]).toHaveTextContent("Could not read Codex's settings");
    expect(screen.getByTestId("import-nothing")).toBeInTheDocument();
  });
});

describe("the list", () => {
  it("one row per server: tick, name, tool, what it runs, its keys; ticks follow the server", async () => {
    await openSheet([PACKAGE, KEYED, row({ id: "codex:off", tool: "codex", name: "off", tick: false })]);
    expect(tick("md-tools").checked).toBe(true);
    expect(tick("notes").checked).toBe(true);
    expect(tick("off").checked).toBe(false);
    expect(rowEl("notes")).toHaveTextContent("Codex");
    expect(rowEl("md-tools")).toHaveTextContent("Claude Code");
    expect(rowEl("notes")).toHaveTextContent("Has 1 key.");
    expect(rowEl("md-tools")).not.toHaveTextContent("key");
  });

  it("says how many keys in the plural too", async () => {
    await openSheet([{ ...KEYED, keys: 3 }]);
    expect(rowEl("notes")).toHaveTextContent("Has 3 keys.");
  });

  it("the add button counts the ticks and is disabled at none", async () => {
    await openSheet([PACKAGE, KEYED]);
    expect(addButton()).toHaveTextContent("Add 2 connections");
    fireEvent.click(tick("notes"));
    expect(addButton()).toHaveTextContent("Add 1 connection");
    expect(addButton()).not.toHaveTextContent("connections");
    fireEvent.click(tick("md-tools"));
    expect(addButton()).toBeDisabled();
    fireEvent.click(addButton());
    expect(addSpy).not.toHaveBeenCalled();
  });

  it("Not now closes and adds nothing", async () => {
    await openSheet([PACKAGE]);
    fireEvent.click(screen.getByTestId("import-not-now"));
    expect(screen.queryByTestId("cap-import-sheet")).toBeNull();
    expect(addSpy).not.toHaveBeenCalled();
  });

  it("rows already here sit below the list, unticked and unsendable", async () => {
    await openSheet([PACKAGE, row({ id: "codex:already", tool: "codex", name: "already", here: true, tick: false }),
      row({ id: "codex:too", tool: "codex", name: "too", here: true, tick: false })]);
    expect(screen.getAllByTestId("import-row")).toHaveLength(1);
    expect(screen.getByTestId("import-here").textContent).toMatch(/Already here, so not listed: .*already.*, .*too/);
    await addAndGetResults([{ id: PACKAGE.id, state: "on", tools: 1 }]);
    expect(addSpy.mock.calls[0][0].map(s => s.id)).toEqual([PACKAGE.id]);
  });

  it("every part of a server's line shows, an argument with a space reads as one", async () => {
    const many = Array.from({ length: 40 }, (_, i) => `--flag-${i}`);
    await openSheet([{ ...PROGRAM, arguments: [...many, "two words", ""] }]);
    const shown = rowEl("my-server").textContent ?? "";
    for (const flag of many) expect(shown).toContain(flag);
    expect(shown).toContain('"two words" ""');
  });
});

describe("what the row shows is what the POST adds", () => {
  it("a ticked row sends exactly its id and digest from the scan; an unticked one sends nothing", async () => {
    await openSheet([PACKAGE, KEYED, REMOTE]);
    fireEvent.click(tick("notes"));
    await addAndGetResults([{ id: PACKAGE.id, state: "on", tools: 2 }, { id: REMOTE.id, state: "needs_sign_in" }]);
    expect(addSpy).toHaveBeenCalledTimes(1);
    expect(addSpy.mock.calls[0][0]).toEqual([
      { id: PACKAGE.id, digest: PACKAGE.digest, keys: {} }, { id: REMOTE.id, digest: REMOTE.digest, keys: {} }]);
  });

  it("the second scan's digest is the one sent", async () => {
    await openSheet([PACKAGE]);
    await addAndGetResults([{ id: PACKAGE.id, state: "changed" }]);
    scanSpy.mockResolvedValueOnce(scan([{ ...PACKAGE, digest: "new-digest" }]));
    fireEvent.click(screen.getByTestId("import-rescan"));
    await screen.findByTestId("import-add");
    addSpy.mockResolvedValue({ results: [{ id: PACKAGE.id, state: "on", tools: 1 }] });
    fireEvent.click(addButton());
    await screen.findByTestId("import-done");
    expect(addSpy.mock.calls[1][0]).toEqual([{ id: PACKAGE.id, digest: "new-digest", keys: {} }]);
  });

  it("a ticked refused row can't exist: its tick is disabled and it is not sent, whatever the server's tick says", async () => {
    await openSheet([PACKAGE, row({ id: "codex:bad", tool: "codex", name: "bad", refused: "transport", tick: true })]);
    expect(tick("bad").checked).toBe(false);
    expect(tick("bad")).toBeDisabled();
    expect(addButton()).toHaveTextContent("Add 1 connection");
    fireEvent.click(tick("bad"));
    await addAndGetResults([{ id: PACKAGE.id, state: "on", tools: 1 }]);
    expect(addSpy.mock.calls[0][0].map(s => s.id)).toEqual([PACKAGE.id]);
  });

  it("opaque fields stay out of the page: no id or same_as in the markup, a name is text", async () => {
    const hostile = "codex:<img src=x onerror=alert(1)>";
    await openSheet([row({ id: hostile, tool: "codex", name: "<b>plain</b>" }),
      row({ id: "codex:second", tool: "codex", name: "second", same_as: hostile, tick: false })]);
    const sheet = screen.getByTestId("cap-import-sheet");
    expect(sheet.innerHTML).not.toContain("onerror");
    expect(sheet.querySelector("img")).toBeNull();
    expect(sheet.querySelector("b")).toBeNull();
    expect(sheet.textContent).toContain("<b>plain</b>");
    expect(sheet.innerHTML).not.toContain("codex:second");
    await addAndGetResults([{ id: hostile, state: "here" }]);
    expect(addSpy.mock.calls[0][0][0].id).toBe(hostile);
    expect(screen.getByTestId("cap-import-sheet").innerHTML).not.toContain("onerror");
  });

  it("no ⌘⏎: the add is a click", async () => {
    await openSheet([PACKAGE]);
    fireEvent.keyDown(tick("md-tools"), { key: "Enter", metaKey: true });
    expect(addSpy).not.toHaveBeenCalled();
  });
});

describe("a custom program", () => {
  it("says the user's exact words, then what it runs, then its env names, in the warning tone", async () => {
    await openSheet([PROGRAM]);
    const words = "Runs this program as your other tool does, with no sandbox.";
    expect(capabilityListMessages.en.import_program).toBe(words);
    const warning = within(rowEl("my-server")).getByTestId("import-program");
    expect(warning).toHaveTextContent(words);
    expect(warning.className).toContain("text-warning");
    const shown = rowEl("my-server").textContent ?? "";
    expect(shown.indexOf(words)).toBeLessThan(shown.indexOf("/opt/tools/run.sh --port 9000"));
    expect(shown).toContain('"two words"');
    expect(within(rowEl("my-server")).getByTestId("import-env")).toHaveTextContent("FOO_TOKEN, PYTHONPATH");
  });

  it("is never ticked by default, even if a server's tick said so; a tick by hand sends it", async () => {
    await openSheet([{ ...PROGRAM, tick: true }, PACKAGE]);
    expect(tick("my-server").checked).toBe(false);
    expect(addButton()).toHaveTextContent("Add 1 connection");
    fireEvent.click(tick("my-server"));
    await addAndGetResults([{ id: PROGRAM.id, state: "added", server_id: 7 }, { id: PACKAGE.id, state: "on", tools: 1 }]);
    expect(addSpy.mock.calls[0][0].map(s => s.digest)).toEqual([PROGRAM.digest, PACKAGE.digest]);
  });

  it("its result says it isn't tested and where a failed start shows", async () => {
    await openSheet([{ ...PROGRAM, tick: true }]);
    fireEvent.click(tick("my-server"));
    await addAndGetResults([{ id: PROGRAM.id, state: "added", server_id: 7 }]);
    expect(screen.getByTestId("import-result-added")).toHaveTextContent("if it can't start, its row in Capabilities says so");
    expect(screen.getByTestId("import-result-added").textContent).toContain("no sandbox");
  });
});

describe("the other rows", () => {
  it("a keyless package names itself and has no network, in words", async () => {
    await openSheet([row({ id: "claude_code:p", name: "p", arguments: ["-y", "--yes", "real-pkg@1.2.3", "--opt", "v"] })]);
    const shown = rowEl("p").textContent ?? "";
    expect(shown).toContain("npm package");
    expect(shown).toContain("real-pkg@1.2.3");
    expect(shown).toContain("no network");
    expect(shown).toContain("in a sandbox");
    expect(shown).toContain("--opt v");
    const sentence = within(rowEl("p")).getByTestId("import-runs").textContent ?? "";
    expect(sentence).toContain("real-pkg@1.2.3");
    expect(sentence).not.toContain("--yes");
    expect(sentence).not.toContain("-y");
  });

  it("a package with a key has the network on, and uvx reads as PyPI", async () => {
    await openSheet([KEYED]);
    const shown = rowEl("notes").textContent ?? "";
    expect(shown).toContain("PyPI package");
    expect(shown).toContain("notes-mcp==0.9.1");
    expect(shown).toContain("the network on");
    expect(shown).not.toContain("no network");
  });

  it("a remote shows its address", async () => {
    await openSheet([REMOTE]);
    expect(rowEl("tracker")).toHaveTextContent("mcp.tracker.example");
    expect(rowEl("tracker").textContent).toContain("https://mcp.tracker.example");
  });

  it.each([
    ["unreadable", "can't read"], ["cannot_pin", "can't be locked"], ["unsafe_setting", "can change what runs"],
    ["runs_a_helper", "helper"], ["transport", "streamable HTTP"], ["something_new", "can't add this one"],
  ])("a row refused for %s is listed, can't be ticked, and says why plainly", async (code, reason) => {
    await openSheet([row({ id: "codex:bad", tool: "codex", name: "bad", refused: code, refused_part: "bad", tick: false })]);
    expect(tick("bad")).toBeDisabled();
    expect(rowEl("bad")).toHaveTextContent(reason);
    expect(rowEl("bad").textContent).not.toContain(code);
    expect(within(rowEl("bad")).queryByTestId("import-runs")).toBeNull();
  });

  it("a refused row names the part when it isn't just the server, and what it would have run", async () => {
    await openSheet([row({ id: "codex:bad", tool: "codex", name: "bad", refused: "unsafe_setting", refused_part: "bad: LD_PRELOAD", tick: false })]);
    expect(rowEl("bad").textContent).toContain("bad: LD_PRELOAD");
    expect(rowEl("bad").textContent).toContain("npx -y bad@1.0.0");
  });

  it("a refused part that is only the server's name isn't said twice", async () => {
    await openSheet([row({ id: "codex:bad", tool: "codex", name: "bad", command: null, arguments: [], refused: "unreadable",
      refused_part: "bad", tick: false })]);
    expect(rowEl("bad").textContent?.match(/bad/g)).toHaveLength(1);
  });

  it("off in Codex and tool limits are said in words and start unticked; a tick takes them", async () => {
    await openSheet([row({ id: "codex:off", tool: "codex", name: "off", on_there: false, tick: false }),
      row({ id: "codex:limits", tool: "codex", name: "limits", tool_limits: true, tick: false })]);
    expect(rowEl("off")).toHaveTextContent("It's off in Codex");
    expect(rowEl("limits")).toHaveTextContent("limits which of its tools run");
    expect(rowEl("off").textContent).not.toContain("limits");
    expect(rowEl("limits").textContent).not.toContain("off in");
    expect(addButton()).toBeDisabled();
    fireEvent.click(tick("off"));
    fireEvent.click(tick("limits"));
    expect(addButton()).toHaveTextContent("Add 2 connections");
  });

  it("the second tool's copy follows the server's fields, and says which it copies by name", async () => {
    await openSheet([PACKAGE, row({ id: "codex:copy", tool: "codex", name: "copy", same_as: PACKAGE.id, tick: false })]);
    expect(tick("copy").checked).toBe(false);
    expect(tick("copy")).not.toBeDisabled();
    expect(rowEl("copy").textContent).toMatch(/Same server as .*md-tools.* in Claude Code/);
    expect(rowEl("copy").textContent).not.toContain(PACKAGE.id);
  });

  it("env names show on a package and as headers on a remote; nothing else claims them", async () => {
    await openSheet([KEYED, { ...REMOTE, env: ["Authorization"] }, PACKAGE]);
    expect(within(rowEl("notes")).getByTestId("import-env")).toHaveTextContent("NOTES_KEY");
    expect(within(rowEl("tracker")).getByTestId("import-env")).toHaveTextContent("Headers it sends: Authorization");
    expect(within(rowEl("md-tools")).queryByTestId("import-env")).toBeNull();
  });
});

describe("keys a row asks for", () => {
  const input = (rowName: string, key: string) =>
    within(rowEl(rowName)).getByLabelText<HTMLInputElement>(key);

  it("a password input for each name, sent only in that row's keys", async () => {
    const twin = row({ id: "codex:twin", tool: "codex", name: "twin", asks: ["API_KEY"], network: true });
    await openSheet([ASKING, twin]);
    expect(input("asking", "API_KEY").type).toBe("password");
    expect(input("asking", "OTHER").type).toBe("password");
    fireEvent.change(input("asking", "API_KEY"), { target: { value: "s3cret-a" } });
    fireEvent.change(input("asking", "OTHER"), { target: { value: "s3cret-b" } });
    fireEvent.change(input("twin", "API_KEY"), { target: { value: "s3cret-c" } });
    await addAndGetResults([{ id: ASKING.id, state: "on", tools: 1 }, { id: twin.id, state: "on", tools: 1 }]);
    expect(addSpy.mock.calls[0][0]).toEqual([
      { id: ASKING.id, digest: ASKING.digest, keys: { API_KEY: "s3cret-a", OTHER: "s3cret-b" } },
      { id: twin.id, digest: twin.digest, keys: { API_KEY: "s3cret-c" } }]);
  });

  it("an unticked row's value goes nowhere, and its input needs the tick", async () => {
    await openSheet([ASKING, PACKAGE]);
    fireEvent.change(input("asking", "API_KEY"), { target: { value: "s3cret-a" } });
    fireEvent.click(tick("asking"));
    expect(input("asking", "API_KEY")).toBeDisabled();
    await addAndGetResults([{ id: PACKAGE.id, state: "on", tools: 1 }]);
    expect(JSON.stringify(addSpy.mock.calls[0][0])).not.toContain("s3cret-a");
  });

  it("an empty one is left out: the server answers needs_keys, by name", async () => {
    await openSheet([ASKING]);
    fireEvent.change(input("asking", "OTHER"), { target: { value: "   " } });
    await addAndGetResults([{ id: ASKING.id, state: "needs_keys", keys: ["API_KEY", "OTHER"] }]);
    expect(addSpy.mock.calls[0][0][0].keys).toEqual({});
    expect(screen.getByTestId("import-result-needs_keys").textContent).toContain("API_KEY, OTHER");
    expect(screen.getByTestId("import-rescan")).toBeInTheDocument();
  });

  it("a key name like __proto__ is only a name", async () => {
    await openSheet([row({ id: "codex:odd", tool: "codex", name: "odd", asks: ["__proto__"] })]);
    expect(input("odd", "__proto__").value).toBe("");
    fireEvent.change(input("odd", "__proto__"), { target: { value: "s3cret-p" } });
    await addAndGetResults([{ id: "codex:odd", state: "on", tools: 1 }]);
    expect(JSON.stringify(addSpy.mock.calls[0][0][0].keys)).toBe('{"__proto__":"s3cret-p"}');
  });

  it("is never rendered back, logged or kept after the sheet closes", async () => {
    const logs = (["log", "info", "warn", "error", "debug"] as const).map(level => vi.spyOn(console, level));
    await openSheet([ASKING]);
    fireEvent.change(input("asking", "API_KEY"), { target: { value: "s3cret-a" } });
    await addAndGetResults([{ id: ASKING.id, state: "failed", stage: "test", detail: "no answer" }]);
    expect(document.body.innerHTML).not.toContain("s3cret-a");
    expect(JSON.stringify(logs.map(spy => spy.mock.calls))).not.toContain("s3cret-a");
    expect(JSON.stringify({ ...localStorage })).not.toContain("s3cret-a");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("s3cret-a");
    logs.forEach(spy => spy.mockRestore());
    // Another scan and another opening start empty.
    scanSpy.mockResolvedValue(scan([ASKING]));
    fireEvent.click(screen.getByTestId("import-done"));
    fireEvent.click(screen.getByTestId("cap-add-import"));
    await screen.findByTestId("import-add");
    expect(input("asking", "API_KEY").value).toBe("");
  });

  it("a scan again after a result starts empty", async () => {
    await openSheet([ASKING]);
    fireEvent.change(input("asking", "API_KEY"), { target: { value: "s3cret-a" } });
    await addAndGetResults([{ id: ASKING.id, state: "needs_keys", keys: ["OTHER"] }]);
    fireEvent.click(screen.getByTestId("import-rescan"));
    await screen.findByTestId("import-add");
    expect(input("asking", "API_KEY").value).toBe("");
  });
});

describe("results", () => {
  const ROWS = ["on", "needs_sign_in", "failed", "blocked", "added", "refused", "here", "needs_keys", "gone", "changed"]
    .map(state => row({ id: `codex:${state}`, tool: "codex", name: `srv-${state}` }));
  const RESULTS: ImportResult[] = [
    { id: "codex:on", state: "on", tools: 3 }, { id: "codex:needs_sign_in", state: "needs_sign_in" },
    { id: "codex:failed", state: "failed", stage: "test", detail: "no answer" }, { id: "codex:blocked", state: "blocked" },
    { id: "codex:added", state: "added", server_id: 3 }, { id: "codex:refused", state: "refused", code: "cannot_pin" },
    { id: "codex:here", state: "here" }, { id: "codex:needs_keys", state: "needs_keys", keys: ["K"] },
    { id: "codex:gone", state: "gone" }, { id: "codex:changed", state: "changed" }];

  it("each state has its own line, naming the server", async () => {
    await openSheet(ROWS);
    await addAndGetResults(RESULTS);
    const expected: Record<string, RegExp> = {
      on: /Added .*srv-on.* tested, 3 tools, switched on/, needs_sign_in: /stays off until you sign in/,
      failed: /did not pass \(test\): no answer/, blocked: /scan found a dangerous pattern/,
      added: /no sandbox/, refused: /can't be locked/, here: /already here/,
      needs_keys: /needs K/, gone: /no longer in/, changed: /changed .* after this list was read/ };
    for (const [state, words] of Object.entries(expected)) {
      const line = screen.getByTestId(`import-result-${state}`);
      expect(line.dataset.state).toBe(state);
      expect(line.textContent).toMatch(words);
      expect(line.textContent).toContain(`srv-${state}`);
    }
  });

  it.each(["gone", "changed"] as const)("%s says to scan again and offers it; the new scan shows the list", async (state) => {
    await openSheet([PACKAGE]);
    await addAndGetResults([{ id: PACKAGE.id, state }]);
    expect(screen.getByTestId(`import-result-${state}`)).toHaveTextContent("Scan again");
    scanSpy.mockClear();
    scanSpy.mockResolvedValue(scan([KEYED]));
    fireEvent.click(screen.getByTestId("import-rescan"));
    await screen.findByTestId("import-add");
    expect(scanSpy).toHaveBeenCalledTimes(1);
    expect(rowEl("notes")).toBeInTheDocument();
    expect(screen.queryByTestId("import-done")).toBeNull();
  });

  it("nothing to scan for: no scan-again offer", async () => {
    await openSheet([PACKAGE]);
    await addAndGetResults([{ id: PACKAGE.id, state: "on", tools: 1 }]);
    expect(screen.queryByTestId("import-rescan")).toBeNull();
  });

  it("the list of Capabilities reads again after an add, and Done closes", async () => {
    await openSheet([PACKAGE]);
    listSpy.mockClear();
    await addAndGetResults([{ id: PACKAGE.id, state: "on", tools: 1 }]);
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("import-done"));
    expect(screen.queryByTestId("cap-import-sheet")).toBeNull();
  });

  it("an add that fails says so, keeps the ticks and still reads the list again", async () => {
    await openSheet([PACKAGE]);
    listSpy.mockClear();
    addSpy.mockRejectedValue(new Error("offline"));
    fireEvent.click(addButton());
    expect(await screen.findByTestId("import-add-failed")).toHaveTextContent("Could not add them");
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(1));
    expect(tick("md-tools").checked).toBe(true);
    expect(screen.queryByTestId("import-done")).toBeNull();
  });

  it("while adding, nothing closes the sheet and a second click sends nothing", async () => {
    await openSheet([PACKAGE]);
    let finish: (value: { results: ImportResult[] }) => void = () => {};
    addSpy.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    fireEvent.click(addButton());
    expect(addButton()).toBeDisabled();
    expect(screen.getByTestId("import-not-now")).toBeDisabled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: i18n.t("kit.close") })).toBeDisabled();
    expect(screen.getByTestId("cap-import-sheet")).toBeInTheDocument();
    fireEvent.click(addButton());
    expect(addSpy).toHaveBeenCalledTimes(1);
    finish({ results: [{ id: PACKAGE.id, state: "on", tools: 1 }] });
    await screen.findByTestId("import-done");
  });
});

describe("the footer", () => {
  const foot = () => screen.getByTestId("import-foot").textContent ?? "";

  it("says each one is tested only while no custom program is ticked", async () => {
    await openSheet([PACKAGE, PROGRAM]);
    expect(foot()).toContain("Keys are kept encrypted on this Mac, and the model never sees them.");
    expect(foot()).toContain("Each one is tested once before it is switched on.");
    expect(foot()).not.toContain("custom program");
    fireEvent.click(tick("my-server"));
    expect(foot()).not.toContain("Each one is tested");
    expect(foot()).toContain("A custom program isn't tested: it starts when it is added.");
    fireEvent.click(tick("my-server"));
    expect(foot()).toContain("Each one is tested once before it is switched on.");
  });
});

describe("the words", () => {
  it.each(["zh", "ja", "es", "de", "fr"] as const)("%s has each key, none of them left in English", (language) => {
    const en = capabilityListMessages.en as Record<string, string>;
    const there = capabilityListMessages[language] as Record<string, string>;
    for (const key of Object.keys(en).filter(k => k.startsWith("import_"))) {
      expect(there[key], key).toBeTruthy();
      expect(there[key], key).not.toBe(en[key]);
    }
  });

  it("the sheet opens in another language with its own words", async () => {
    await i18n.changeLanguage("de");
    await openSheet([PROGRAM]);
    expect(within(rowEl("my-server")).getByTestId("import-program").textContent).toBe(capabilityListMessages.de.import_program);
  });
});
