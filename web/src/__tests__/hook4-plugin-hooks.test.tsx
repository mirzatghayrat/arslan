// HOOK-4, the web half of a plugin's hooks (board 8, approved): A, each hook Arslan runs on the install card's Hooks
// row, with one sentence on how hooks run, while hooks that don't run keep CAP8-2's words; B, each one's own switch
// under "Show what's inside", stored through HOOK-1's PUT /capability-hooks and on by default; C, the two ledger
// lines a hook causes, from fixtures (HOOK-3 emits them). Real strings (en); every plugin and command is invented.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "../i18n";
import { capabilitiesApi, type CapabilityRow } from "../api/capabilities";
import type { CapabilityCard, HookRow } from "../api/client.types";
import CapabilitySwitches from "../components/CapabilitySwitches";
import CapabilityProposeCard from "../components/capabilities/CapabilityProposeCard";
import { HookLedgerLine } from "../components/capabilities/HookLedgerLine";
import { capabilityListMessages } from "../locales/capabilityList";

vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn().mockResolvedValue([]), listMcpTools: vi.fn().mockResolvedValue([]),
}));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const RUNS = "Each hook runs in the sandbox with no network, can't change your files, and has 10 seconds. If one fails or "
  + "runs out of time, Arslan asks you instead of going ahead. Scheduled tasks don't run hooks.";
const GUARD = "Can stop a command or ask you first. It can never approve anything for you.";
const CONTEXT = "Adds text for the model, marked as not from you.";

const hook = (id: string, event: string, command: string, over: Partial<HookRow> = {}): HookRow => ({
  id, event, when: null, matcher: null, matches: ["*"], matches_note: null, command, args: null, if: null, timeout: 10,
  kind: "supported", on: true, note: "", ...over });
const GUARDED = hook("0", "PreToolUse", "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/no_force_push.py", { matcher: "Bash",
  matches: ["run_command"] });
const RULES = hook("1", "SessionStart", "cat ${CLAUDE_PLUGIN_ROOT}/hooks/rules.md", { matches: ["startup"] });
const UNSURE = hook("2", "PreToolUse", "./hooks/check.sh", { matcher: "Ba.*", matches_note: "Can't tell…" });
const QUIET = hook("3", "Notification", "./hooks/ping.sh", { kind: "wont_run", on: false });

const CARD: CapabilityCard = {
  kind: "plugin", name: "safe-git", summary: "Guards git", source_url: null, repo: null, version: null,
  license: { spdx: "MIT", read_from: "LICENSE" }, stars: null, pushed_days: null, runtime: "plugin", runtime_download: null,
  remote_host: null, network: false, folders: [], keys: [], why: "", retry: "", skills: [], connections: [],
};
const card = (rows: HookRow[]) => render(<CapabilityProposeCard card={{ ...CARD, hooks: rows.map(r => r.event), hook_rows: rows }}
  callId="c1" onConfirm={vi.fn()} onCancel={vi.fn()} />);

describe("A: the install card's Hooks row", () => {
  it("shows each hook Arslan runs: when, on what, the exact command line, and what it can do", () => {
    card([GUARDED, RULES, UNSURE]);
    const entries = screen.getAllByTestId("hook-entry");
    expect(entries.map(e => e.textContent)).toEqual([
      `Before a tool runs on run_commandpython3 \${CLAUDE_PLUGIN_ROOT}/hooks/no_force_push.py${GUARD}`,
      `When a conversation startscat \${CLAUDE_PLUGIN_ROOT}/hooks/rules.md${CONTEXT}`,
      `Before a tool runs on can't tell; treated as every tool./hooks/check.sh${GUARD}`,
    ]);
    expect(within(entries[0]).getByText("python3 ${CLAUDE_PLUGIN_ROOT}/hooks/no_force_push.py").closest("code")).not.toBeNull();
    // The matcher that can't be told is in the warm colour; a named tool isn't.
    expect(within(entries[2]).getByTestId("hook-entry-on")).toHaveClass("text-ask");
    expect(within(entries[0]).getByTestId("hook-entry-on")).not.toHaveClass("text-ask");
    expect(within(entries[1]).queryByTestId("hook-entry-on")).toBeNull();
    expect(screen.getByTestId("hook-runs-note").textContent).toBe(RUNS);
    expect(screen.getByTestId("import-card-hooks")).not.toHaveTextContent("won't run");
  });

  it("the command line is the command and its arguments, every character shown", () => {
    card([hook("0", "PostToolUse", "fmt", { args: ["--check", "a​b"], matches: ["edit_file", "write_file"] })]);
    const entry = screen.getByTestId("hook-entry");
    expect(entry).toHaveTextContent("After a tool runs on edit_file, write_file");
    expect(entry.querySelector("code")?.textContent).toBe("fmt --check aU+200Bb");
    expect(entry).toHaveTextContent(CONTEXT);
  });

  it("hooks that don't run keep today's words, beside the ones that do", () => {
    card([GUARDED, QUIET]);
    expect(screen.getAllByTestId("hook-entry")).toHaveLength(1);
    expect(screen.getByTestId("import-card-hooks")).toHaveTextContent(
      "1 hook, won't run: Notification, when a notification is sent.Arslan doesn't run hooks.");
  });

  it("with no hook Arslan runs, the row is exactly today's", () => {
    card([QUIET, hook("4", "PostToolUse", "x", { kind: "matches_nothing", on: false, matches: [] })]);
    expect(screen.queryByTestId("hook-entry")).toBeNull();
    expect(screen.queryByTestId("hook-runs-note")).toBeNull();
    expect(screen.getByTestId("import-card-hooks").textContent).toBe("2 hooks, won't run: Notification, when a notification "
      + "is sent; PostToolUse, after a tool runs.Arslan doesn't run hooks. Anything in this plugin that depends on them may not work.");
  });
});

const PLUGIN = (hooks: HookRow[]): CapabilityRow => ({ key: "plugin:p3", section: "plugins", origin: "installed",
  deletable: true, last_used: null, source_id: "p3", reach: null, state: "on", tools: [], switch: "plugin", reason: null,
  fix: null, name: "safe-git", detail: "Guards git", parts: [], hooks });

async function inside(hooks: HookRow[]) {
  vi.spyOn(capabilitiesApi, "list").mockResolvedValue([PLUGIN(hooks)]);
  render(<CapabilitySwitches />);
  fireEvent.click(within(await screen.findByTestId("cap-plugin:p3")).getByText("Show what's inside"));
  return screen.getByTestId("plugin-hooks-plugin:p3");
}

describe("B: each hook's own switch, under Show what's inside", () => {
  it("one row per hook Arslan runs, on by default, with when · match, the command, and the closing line", async () => {
    const box = await inside([GUARDED, RULES, UNSURE, QUIET]);
    expect(within(box).queryByTestId("plugin-hook-3")).toBeNull();            // a hook that doesn't run has no switch
    const rows = ["0", "1", "2"].map(id => within(box).getByTestId(`plugin-hook-${id}`));
    expect(rows[0]).toHaveTextContent("Before a tool runs · run_command");
    expect(rows[0]).toHaveTextContent("python3 …/hooks/no_force_push.py");
    expect(rows[1]).toHaveTextContent("When a conversation starts · every conversation");
    expect(rows[2]).toHaveTextContent("Before a tool runs · can't tell; every tool");
    for (const r of rows) {
      const toggle = within(r).getByRole("switch");
      expect(toggle).toBeChecked();
      expect(r).toHaveTextContent("On");
      expect(toggle.closest("label")).toHaveClass("min-h-[44px]");
    }
    expect(within(box).getByRole("switch", { name: "Run this hook: Before a tool runs, run_command" })).toBe(
      within(rows[0]).getByRole("switch"));
    expect(within(box).queryByTestId("plugin-hook-last")).toBeNull();        // nothing recorded: no line, nothing invented
    expect(box).toHaveTextContent("If a hook changes in an update, the plugin is switched off until you look at its card again.");
  });

  it("flipping one stores it through HOOK-1's switch, and the stored value is what shows next time", async () => {
    const put = vi.spyOn(capabilitiesApi, "switchHook").mockResolvedValue({ owner: "plugin:p3", id: "0", on: false });
    const box = await inside([GUARDED, RULES]);
    const toggle = within(within(box).getByTestId("plugin-hook-0")).getByRole("switch");
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).not.toBeChecked());
    expect(put).toHaveBeenCalledWith("plugin:p3", "0", false);
    expect(within(box).getByTestId("plugin-hook-0")).toHaveTextContent("Off");
    expect(within(within(box).getByTestId("plugin-hook-1")).getByRole("switch")).toBeChecked();
    cleanup();
    const again = await inside([{ ...GUARDED, on: false }, RULES]);
    expect(within(within(again).getByTestId("plugin-hook-0")).getByRole("switch")).not.toBeChecked();
  });

  it("a switch the server refuses stays as it was, and says so", async () => {
    vi.spyOn(capabilitiesApi, "switchHook").mockRejectedValue(new Error("409"));
    const box = await inside([GUARDED]);
    const toggle = within(box).getByRole("switch");
    fireEvent.click(toggle);
    expect(await within(box).findByRole("alert")).toHaveTextContent("Couldn't switch this hook. Try again.");
    expect(toggle).toBeChecked();
  });

  it.each([
    [{ ran_today: 3, stopped_today: 0, blocked: null }, true, "Ran 3 times today", "text-muted-foreground"],
    [{ ran_today: 3, stopped_today: 1, blocked: null }, true, "Stopped 1 command today", "text-danger"],
    [{ ran_today: 0, stopped_today: 0, blocked: "network" }, false, "Off · tried to reach the network: blocked", "text-ask"],
    [{ ran_today: 0, stopped_today: 0, blocked: "write" }, true, "tried to write files: blocked", "text-ask"],
  ] as const)("HOOK-3's activity slot, when it has data: %o", async (last, on, text, tone) => {
    const box = await inside([{ ...GUARDED, on, last }]);
    const line = within(box).getByTestId("plugin-hook-last");
    expect(line.textContent).toBe(text);
    expect(line).toHaveClass(tone);
  });

  it("no plugin with only hooks that don't run gets a hooks list", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([PLUGIN([QUIET])]);
    render(<CapabilitySwitches />);
    fireEvent.click(within(await screen.findByTestId("cap-plugin:p3")).getByText("Show what's inside"));
    expect(screen.queryByTestId("plugin-hooks-plugin:p3")).toBeNull();
  });
});

describe("C: the ledger lines a hook causes", () => {
  it("Stopped by a hook: the tool and its argument, then the plugin, the event and the hook's reason", () => {
    render(<HookLedgerLine entry={{ kind: "hook_stopped", tool: "run_command", argument: "git push --force origin main",
      plugin: "safe-git", event: "PreToolUse", reason: "Force-pushing to main isn't allowed here." }} />);
    const [head, line] = [...screen.getByTestId("hook-ledger-line").children];
    expect(head.textContent).toBe("Stopped by a hook run_command git push --force origin main");
    expect(within(head as HTMLElement).getByText("Stopped by a hook")).toHaveClass("text-danger");
    expect(line.textContent).toBe("safe-git · Before a tool runs: “⁨Force-pushing to main isn't allowed here.⁩”"
      .replace("safe-git", "⁨safe-git⁩"));
  });

  it("Asked you: a hook that didn't answer in 10 seconds", () => {
    render(<HookLedgerLine entry={{ kind: "hook_asked", tool: "run_command", argument: "./deploy.sh", plugin: "safe-git",
      event: "PreToolUse", reason: null }} />);
    const el = screen.getByTestId("hook-ledger-line");
    expect(el.dataset.kind).toBe("hook_asked");
    expect(within(el).getByText("Asked you")).toHaveClass("text-ask");
    expect(el.children[1].textContent).toBe(
      "⁨safe-git⁩ · Before a tool runs: didn't answer in 10 seconds, so Arslan asked you.");
  });

  it("a reason can't reorder the sentence around it", () => {
    render(<HookLedgerLine entry={{ kind: "hook_asked", tool: "run_command", argument: "x", plugin: "p‮",
      event: "UserPromptSubmit", reason: "a‮b" }} />);
    const line = screen.getByTestId("hook-ledger-line").children[1].textContent ?? "";
    expect(line).not.toContain("‮");
    expect(line).toContain("When you send a message");
  });
});

describe("the words", () => {
  it.each(["zh", "ja", "es", "de", "fr"] as const)("%s has HOOK-4's keys in its own words", (language) => {
    const en = capabilityListMessages.en as Record<string, string>;
    const there = capabilityListMessages[language] as Record<string, string>;
    const keys = Object.keys(en).filter(key => /^hook(Chip_|On$|Unsure|EveryTool|Can|Runs|MatchUnsure|Every_|Switch|Change|Last_|Ledger_)/
      .test(key));
    expect(keys.length).toBe(28);
    for (const key of keys) {
      expect(there[key], key).toBeTruthy();
      expect(there[key], key).not.toBe(en[key]);
    }
  });
});
