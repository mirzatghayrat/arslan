/**
 * 0.1.58 §1: a reply's steps fold into one footer row under the answer; it opens to the steps
 * in plain words; a reloaded conversation shows the same row and the same list; tokens leave
 * the row for the model's popover; every built-in tool has words in six languages.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { runProcess } = vi.hoisted(() => ({ runProcess: vi.fn() }));
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), api: { runProcess } }));

import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { toUiMessages } from "../api/adapters";
import ReplyFooter from "../components/reply/ReplyFooter";
import { _resetProcessCache } from "../components/reply/ProcessList";
import { group, stepWords, type ProcessEntry } from "../lib/process";
import toolWords from "../lib/toolWords.json";
import { processMessages } from "../locales/process";

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); _resetProcessCache(); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const store = () => useArslanStore.getState();
const SERVER = {
  run_id: 7, status: "recorded", steps: 2, failed: 1, ms: 48000,
  entries: [
    { kind: "note", text: "Looking at the folder first." },
    { kind: "tool", tool: "web_search", ok: true, ms: 400, args_summary: '{"query":"tide tables"}', summary: "2 results",
      detail: { view: "search", query: "tide tables", count: 2, links: [{ title: "A", url: "https://a.example" }], provider: "x", error: null } },
    { kind: "tool", tool: "run_command", ok: false, ms: 800, args_summary: '{"command":"ls"}', summary: "exit 2",
      detail: { view: "command", command: "ls", exit_code: 2, head: { lines: ["one", "two"], more: 3 }, error: "exit 2" } },
  ],
};

function liveTurn() {
  store().handleFrame({ type: "stream_start", source: "arslan", run_id: 7 } as never);
  store().handleFrame({ type: "note", text: "Looking at the folder first." } as never);
  store().handleFrame({ type: "tool_call", tool: "web_search", args_summary: '{"query":"tide tables"}' } as never);
  store().handleFrame({ type: "tool_result", tool: "web_search", ok: true, summary: "2 results" } as never);
  store().handleFrame({ type: "tool_call", tool: "run_command", args_summary: '{"command":"ls"}' } as never);
  store().handleFrame({ type: "tool_result", tool: "run_command", ok: false, summary: "exit 2" } as never);
  store().handleFrame({ type: "stream_chunk", content: "Done." } as never);
  store().handleFrame({ type: "stream_end", message_id: 11, run_id: 7, usage: { tokens_in: 38200, tokens_out: 1900,
    tokens_total: 40100, estimated: false, usd: 0.004, calls: 4, models: [{ model: "deepseek-v4-flash", provider: "deepseek" }] } } as never);
}

describe("the store keeps what the footer needs", () => {
  it("narration becomes a line between steps; steps get their time; the turn its length", () => {
    liveTurn();
    const item = store().items.find((i) => i.id === 11)!;
    expect(item.toolSteps?.map((s) => s.kind ?? s.tool)).toEqual(["note", "web_search", "run_command"]);
    expect(item.toolSteps?.[0].text).toBe("Looking at the folder first.");
    expect(typeof item.toolSteps?.[1].ms).toBe("number");
    expect(typeof item.elapsedMs).toBe("number");
  });

  it("a reloaded reply gets the server's row", () => {
    store().handleFrame({ type: "history", messages: [
      { message_id: 10, role: "user", content: "x", spawn_id: null },
      { message_id: 11, role: "arslan", content: "Done.", spawn_id: null, run_id: 7,
        process: { steps: 2, failed: 1, ms: 48000, usage: null } },
    ] } as never);
    const msg = toUiMessages(store().items).find((m) => m.id === "11" || m.text === "Done.")!;
    expect(msg.process?.summary).toMatchObject({ steps: 2, failed: 1, ms: 48000 });
    expect(msg.process?.runId).toBe(7);
  });
});

function footerFor(liveOrReload: "live" | "reload") {
  if (liveOrReload === "live") liveTurn();
  else store().handleFrame({ type: "history", messages: [{ message_id: 11, role: "arslan", content: "Done.", spawn_id: null, run_id: 7,
    process: { steps: 2, failed: 1, ms: 48000, usage: { tokens_in: 38200, tokens_out: 1900, tokens_total: 40100, estimated: false, usd: 0.004,
      models: [{ model: "deepseek-v4-flash", provider: "deepseek" }] } } }] } as never);
  const msg = toUiMessages(store().items).find((m) => m.text === "Done.")!;
  return render(<ReplyFooter text={msg.text} process={msg.process!} latest onReplay={vi.fn()} />);
}

describe("the footer row", () => {
  it("says what it did in one line, and opens to the steps in plain words", async () => {
    runProcess.mockResolvedValue(SERVER);
    footerFor("live");
    const chip = screen.getByTestId("reply-steps");
    expect(chip).toHaveTextContent('process.steps:{"count":2}');
    expect(chip).toHaveTextContent('process.failed:{"count":1}');
    expect(chip).toHaveTextContent("⚠");
    fireEvent.click(chip);
    const list = await screen.findByTestId("process-list");
    await waitFor(() => expect(runProcess).toHaveBeenCalledWith(7));
    expect(within(list).getByTestId("process-note")).toHaveTextContent("Looking at the folder first.");
    const steps = within(list).getAllByTestId("process-step");
    expect(steps[0]).toHaveTextContent('process.t_web_search_x:{"x":"tide tables"}');
    fireEvent.click(within(steps[1]).getByRole("button"));
    const detail = within(steps[1]).getByTestId("step-detail");
    expect(detail).toHaveAttribute("data-view", "command");
    expect(detail).toHaveTextContent("ls");
    expect(detail).toHaveTextContent('process.moreLines:{"count":3}');
    expect(detail.textContent).not.toContain('{"command"');                // never the call's JSON
    expect(within(list).queryByTestId("step-raw")).toBeNull();               // raw only when the server sends it
  });

  it("a reloaded reply shows the same row and the same list as the live one", async () => {
    runProcess.mockResolvedValue(SERVER);
    const a = footerFor("live");
    fireEvent.click(screen.getByTestId("reply-steps"));
    await screen.findAllByTestId("process-step");
    const liveRow = screen.getByTestId("reply-steps").textContent!.replace(/ · .*?(?=›|$)/, "");
    const liveList = screen.getByTestId("process-list").textContent;
    a.unmount();
    useArslanStore.setState(initialArslanState(), true);
    footerFor("reload");
    fireEvent.click(screen.getByTestId("reply-steps"));
    await screen.findAllByTestId("process-step");
    expect(screen.getByTestId("reply-steps").textContent!.replace(/ · .*?(?=›|$)/, "")).toBe(liveRow);
    expect(screen.getByTestId("process-list").textContent).toBe(liveList);
  });

  it("tokens are not on the row; the model name opens what the turn used", () => {
    footerFor("live");
    const footer = screen.getByTestId("reply-footer");
    expect(footer.textContent).not.toMatch(/tok|38\.2k|\$/);
    fireEvent.click(screen.getByTestId("reply-model"));
    const usage = screen.getByTestId("reply-usage");
    expect(usage).toHaveTextContent('process.callsN:{"count":4}');
    expect(usage).toHaveTextContent("38.2k");
    expect(usage).toHaveTextContent("$0.004");
    expect(usage).toHaveTextContent("process.inputWhy");
  });

  it("⋯ holds the full trace and the downloads; an older reply shows copy and ⋯ only on hover", () => {
    const onReplay = vi.fn();
    liveTurn();
    const msg = toUiMessages(store().items).find((m) => m.text === "Done.")!;
    const { rerender } = render(<ReplyFooter text={msg.text} process={msg.process!} latest onReplay={onReplay} />);
    fireEvent.click(screen.getByTestId("reply-more"));
    fireEvent.click(screen.getByTestId("reply-replay"));
    expect(onReplay).toHaveBeenCalledWith(7);
    rerender(<ReplyFooter text={msg.text} process={msg.process!} latest={false} onReplay={onReplay} />);
    expect(screen.getByTestId("reply-more").parentElement?.parentElement?.className).toContain("group-hover/reply:opacity-100");
  });

  it("a reply that used no tool has no steps chip", () => {
    render(<ReplyFooter text="hi" process={{ runId: 3, entries: [], summary: { steps: 0, failed: 0, ms: 900, usage: null } }} latest />);
    expect(screen.queryByTestId("reply-steps")).toBeNull();
  });
});

describe("words", () => {
  const t = (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k);
  it("every built-in tool has its words in all six languages", () => {
    for (const [tool, w] of Object.entries(toolWords as Record<string, { arg?: string }>)) {
      if (tool === "_comment") continue;
      for (const [lang, words] of Object.entries(processMessages)) {
        expect((words as Record<string, string>)[`t_${tool}`], `${lang} t_${tool}`).toBeTruthy();
        if (w.arg) expect((words as Record<string, string>)[`t_${tool}_x`], `${lang} t_${tool}_x`).toBeTruthy();
      }
    }
    const en = Object.keys(processMessages.en).sort();
    for (const words of Object.values(processMessages)) expect(Object.keys(words).sort()).toEqual(en);
  });

  it("never shows a tool's key with its raw summary (the old 'whats_new ok')", () => {
    expect(stepWords({ tool: "whats_new", argsSummary: "{}", status: "ok" }, t)).toBe("process.t_whats_new");
    expect(stepWords({ tool: "read_file", argsSummary: '{"path": "notes.md"}', status: "ok" }, t)).toBe('process.t_read_file_x:{"x":"notes.md"}');
    expect(stepWords({ tool: "web_extract", argsSummary: '{"url": "https://www.example.org/a"}', status: "ok" }, t))
      .toBe('process.t_web_extract_x:{"x":"example.org"}');
    // a cut-off args_summary still yields its value
    expect(stepWords({ tool: "run_command", argsSummary: '{"command": "ls -la ~/Arslan', status: "ok" }, t)).toContain("ls -la");
    expect(stepWords({ tool: "mcp_7_read_data", argsSummary: "{}", status: "ok" }, t)).toBe('process.mcp:{"x":"read_data"}');
  });

  it("consecutive reads fold into one line; a note or another kind of step breaks the run", () => {
    const e = (tool: string): ProcessEntry => ({ kind: "tool", tool, status: "ok" });
    const items = group([e("read_file"), e("list_dir"), e("read_file"), { kind: "note", status: "ok", text: "now" }, e("read_file"), e("run_command")]);
    expect(items.map((i) => i.kind === "group" ? `group:${i.entries.length}` : i.kind === "tool" ? i.tool : "note"))
      .toEqual(["group:3", "note", "read_file", "run_command"]);
  });
});

/** The old usage chip's honesty rules, now on the model popover (0.1.58 decision 3). */
describe("what the turn used", () => {
  const footer = (usage: Record<string, unknown>) => render(<ReplyFooter text="x" latest
    process={{ runId: 1, entries: [], summary: { steps: 0, failed: 0, ms: 1000, usage: usage as never } }} />);
  it("names every model that ran, not only the busiest", () => {
    footer({ tokens_in: 1, tokens_out: 1, tokens_total: 2, estimated: false, usd: null,
      models: [{ model: "deepseek-v4-flash", provider: "deepseek" }, { model: "gemini-2.5-pro", provider: "google" }] });
    expect(screen.getByTestId("reply-model")).toHaveTextContent("deepseek-v4-flash + gemini-2.5-pro");
  });
  it("unknown cost is never shown as $0, and estimates say ≈", () => {
    footer({ tokens_in: 2000, tokens_out: null, tokens_total: 2000, estimated: true, usd: null,
      models: [{ model: "local", provider: "ollama" }] });
    fireEvent.click(screen.getByTestId("reply-model"));
    const usage = screen.getByTestId("reply-usage");
    expect(usage.textContent).not.toContain("$");
    expect(usage).toHaveTextContent("process.unknown");
    expect(usage).toHaveTextContent("≈ 2k");
  });
  it("no model, no name (a frame from before models were reported)", () => {
    footer({ tokens_in: 1, tokens_out: 1, tokens_total: 2, estimated: false, usd: 0 });
    expect(screen.queryByTestId("reply-model")).toBeNull();
  });
});
