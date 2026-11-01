/**
 * INB7-a (v0.1.64): Activity is now Progress (「进展」), and its top row is board F's (the INB7 board; the user's go-ahead, relayed
 * 2026-11-01: 「INB7 a–f can go ahead on F as drawn」). It leads with what waits on you, keeps the four work tiles, and the cost tile
 * carries a bar of the cost by model that opens the by-model table in place. A model keeps its colour when the range changes, so a
 * reader who learned "Claude is blue" is not misled by a repaint. Real English (and two other languages), so a raw key fails.
 */
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, request } = vi.hoisted(() => ({ getUsageSummary: vi.fn(), listRuns: vi.fn(), request: vi.fn() }));
vi.mock("../api/client", () => ({ api: { getUsageSummary, listRuns }, request }));

import ActivityView from "../components/ActivityView";
import Sidebar from "../components/Sidebar";
import UsageCard from "../components/UsageCard";
import { useWaiting, type WaitingView } from "../hooks/useWaiting";
import { SECTIONS } from "../lib/sections";
import { useActivityStore } from "../stores/activityStore";

type Row = { provider: string | null; model: string | null; scope: string; tokens_total: number; usd: number | null; estimated_any: boolean };
const row = (model: string | null, usd: number | null, tokens = 10_000, scope = "answer", provider = "deepseek"): Row =>
  ({ provider, model, scope, tokens_total: tokens, usd, estimated_any: false });
const BANDS = ["<10s", "10–30s", "30s–1m", "1–3m", "3–10m", ">10m"];
const summary = (rows: Row[]) => ({
  range: "7d", daily: [], not_covered: ["optimizer"], rows, estimated_any: false,
  tokens_total: rows.reduce((n, r) => n + r.tokens_total, 0), usd_total: rows.reduce((n, r) => n + (r.usd ?? 0), 0),
  runs: { total: 5, done: 4, failed: 1, stopped: 0, running: 0, p50_ms: 4000, p95_ms: 9000 },
  bin_seconds: 3600, duration_bands: BANDS,
  bins: [{ start_ts: 1_790_000_000, runs: 5, failed: 1, tokens_total: 96_000, durations: [3, 2, 0, 0, 0, 0] }],
});
/** A week: one model used for two things, one priced model, one local model with no price. */
const WEEK = [row("deepseek-v4-pro", 0.30, 60_000), row("deepseek-v4-pro", 0.02, 4_000, "memory_facts"),
  row("claude-sonnet-5-5", 0.60, 20_000, "answer", "anthropic"), row("qwen3", null, 2_000, "spawn", "ollama")];
const waiting = (over: Partial<WaitingView> = {}): WaitingView =>
  ({ count: 4, conversations: ["c1", "c2"], projects: ["p1"], scheduled: [9], loaded: true, ...over });
const sidebarProps = (over: Partial<React.ComponentProps<typeof Sidebar>> = {}): React.ComponentProps<typeof Sidebar> => ({
  threads: [], activeThreadId: "", onSelectThread: vi.fn(), onAddThread: vi.fn(), activeSection: "arslan", onChangeSection: vi.fn(),
  onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(), backendStatus: "online", ...over,
});
const NAMES: Record<string, string> = { en: "Progress", zh: "进展", ja: "進捗", de: "Fortschritt", es: "Progreso", fr: "Avancement" };
const OLD_NAMES: Record<string, string[]> = { en: ["Activity"], zh: ["活动", "动态"], ja: ["アクティビティ"], de: ["Aktivität"],
  es: ["Actividad"], fr: ["Activité"] };

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "7d", filter: {}, openRunId: null, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockResolvedValue(summary(WEEK));
  listRuns.mockResolvedValue([]);
  request.mockResolvedValue({ items: [], entries: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("the page is called Progress", () => {
  it("is the section 'progress' in the sidebar, named in six languages", () => {
    expect(SECTIONS as readonly string[]).toContain("progress");
    expect(SECTIONS as readonly string[]).not.toContain("activity");
    for (const language of SUPPORTED_LANGUAGES) {
      expect(i18n.getResource(language, "translation", "nav.progress"), language).toBe(NAMES[language]);
      expect(i18n.getResource(language, "translation", "nav.activity"), language).toBeUndefined();
    }
    const onChangeSection = vi.fn();
    render(<Sidebar {...sidebarProps({ onChangeSection })} />);
    expect(document.getElementById("nav-btn-activity-footer")).toBeNull();
    const entry = document.getElementById("nav-btn-progress-footer")!;
    expect(entry).toHaveTextContent("Progress");
    fireEvent.click(entry);
    expect(onChangeSection).toHaveBeenCalledWith("progress");
  });

  it("is what Settings and a reply's menu point at, in six languages", () => {
    const keys = ["settings.automationElsewhere", "settings.automationOpenActivity", "settings.openActivity",
      "settings.openActivityBtn", "process.openActivity"];
    for (const language of SUPPORTED_LANGUAGES) {
      for (const key of keys) {
        const text = String(i18n.getResource(language, "translation", key));
        expect(text, `${language} ${key}`).toContain(NAMES[language]);
        for (const old of OLD_NAMES[language]) expect(text, `${language} ${key}`).not.toContain(old);
      }
      expect(i18n.getResource(language, "translation", "activityPage.back"), language).toBeUndefined();    // #610 review F6: no reader
    }
  });
});

describe("「要你做」 leads the row", () => {
  it("is the first tile: how many things wait on you, and what they are", async () => {
    render(<UsageCard waiting={waiting()} />);
    const tiles = await screen.findByTestId("usage-kpis");
    const needs = screen.getByTestId("usage-needs");
    expect(tiles.firstElementChild).toBe(needs);
    expect(needs).toHaveTextContent("Needs you");
    expect(within(needs).getByText("4")).toBeTruthy();
    expect(needs).toHaveTextContent("2 conversations · 1 project · 1 scheduled task");
    expect(needs.className).toContain("bg-ask-soft");                                  // amber: something waits for you
  });

  it("leaves out what is not waiting, and says so when nothing is", () => {
    const { rerender } = render(<UsageCard waiting={waiting({ count: 1, conversations: [], projects: [], scheduled: [3] })} />);
    expect(screen.getByTestId("usage-needs")).toHaveTextContent("1 scheduled task");
    expect(screen.getByTestId("usage-needs")).not.toHaveTextContent(/conversation|project/);
    rerender(<UsageCard waiting={waiting({ count: 0, conversations: [], projects: [], scheduled: [] })} />);
    const needs = screen.getByTestId("usage-needs");
    expect(within(needs).getByText("0")).toBeTruthy();
    expect(needs).toHaveTextContent("All caught up");
    expect(needs.className).not.toContain("bg-ask-soft");
  });

  it("says — until the first count arrives, never 'all caught up'", () => {
    render(<UsageCard waiting={waiting({ count: 0, conversations: [], projects: [], scheduled: [], loaded: false })} />);
    const needs = screen.getByTestId("usage-needs");
    expect(within(needs).getByText("—")).toBeTruthy();
    expect(needs).not.toHaveTextContent("All caught up");
  });

  it("counts in the reader's language, singular and plural", async () => {
    await act(async () => { await i18n.changeLanguage("zh"); });
    const { unmount } = render(<UsageCard waiting={waiting()} />);
    expect(screen.getByTestId("usage-needs")).toHaveTextContent("要你做");
    expect(screen.getByTestId("usage-needs")).toHaveTextContent("2 个对话 · 1 个项目 · 1 个定时任务");
    unmount();
    await act(async () => { await i18n.changeLanguage("de"); });
    render(<UsageCard waiting={waiting()} />);
    expect(screen.getByTestId("usage-needs")).toHaveTextContent("2 Unterhaltungen · 1 Projekt · 1 geplante Aufgabe");
  });

  it("is the app's count, handed to the Progress page", async () => {
    render(<ActivityView waiting={waiting({ count: 2, conversations: ["c1"], projects: [], scheduled: [4] })} />);
    const needs = await screen.findByTestId("usage-needs");
    expect(within(needs).getByText("2")).toBeTruthy();
    expect(needs).toHaveTextContent("1 conversation · 1 scheduled task");
  });
});

describe("the count is known only once the server has answered", () => {
  it("is not known while the first poll is out, and is once it answers", async () => {
    let answer: (value: unknown) => void = () => {};
    request.mockImplementation((path: string) => path === "/proactive/summary"
      ? new Promise((resolve) => { answer = resolve; }) : Promise.resolve({}));
    const { result } = renderHook(() => useWaiting());
    expect(result.current.loaded).toBe(false);
    await act(async () => { answer({ open: 0, unread: 0, high: 0, waiting: { count: 0, conversations: [], projects: [], scheduled: [] } }); });
    expect(result.current.loaded).toBe(true);
    expect(result.current.count).toBe(0);
  });

  it("stays unknown when the first poll fails", async () => {
    request.mockRejectedValue(new Error("restarting"));
    const { result } = renderHook(() => useWaiting());
    await waitFor(() => expect(request).toHaveBeenCalledWith("/proactive/summary"));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });     // the failed poll has been handled
    expect(result.current.loaded).toBe(false);
  });
});

describe("the cost tile opens the cost by model", () => {
  it("closes the row, and opens the by-model table in place, under the tiles, with what is not counted", async () => {
    render(<UsageCard waiting={waiting()} />);
    const cost = await screen.findByTestId("usage-cost");
    await waitFor(() => expect(cost).toHaveTextContent("$0.92"));
    const tiles = screen.getByTestId("usage-kpis");
    expect(tiles.children).toHaveLength(6);
    expect(tiles.lastElementChild).toBe(cost);
    expect(cost.tagName).toBe("BUTTON");
    expect(cost).toHaveTextContent("By model");
    expect(cost).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("usage-row")).toBeNull();
    expect(screen.queryByTestId("usage-notcovered")).toBeNull();

    fireEvent.click(cost);
    expect(cost).toHaveAttribute("aria-expanded", "true");
    const table = document.getElementById(cost.getAttribute("aria-controls")!)!;
    expect(within(table).getAllByTestId("usage-row")).toHaveLength(4);
    expect(within(table).getByTestId("usage-notcovered")).toHaveTextContent("optimizer");
    expect(tiles.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(table.compareDocumentPosition(screen.getByTestId("usage-timeline")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(cost);
    expect(cost).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("usage-row")).toBeNull();
  });

  it("draws the priced cost by model, largest first; a call with no price is not in it", async () => {
    render(<UsageCard />);
    const segs = await screen.findAllByTestId("usage-cost-seg");
    expect(segs.map((s) => s.getAttribute("title"))).toEqual(["claude-sonnet-5-5 · $0.60 · 65%", "deepseek-v4-pro · $0.32 · 35%"]);
    expect(Number(segs[0].style.flexGrow) / Number(segs[1].style.flexGrow)).toBeCloseTo(0.60 / 0.32, 2);
  });

  it("gives each model one colour from the chart palette, the same in the bar and in its table rows", async () => {
    render(<UsageCard />);
    const [claude, deepseek] = (await screen.findAllByTestId("usage-cost-seg")).map((s) => s.style.background);
    expect(claude).toMatch(/^var\(--series-[123]\)$/);
    expect(deepseek).toMatch(/^var\(--series-[123]\)$/);
    expect(claude).not.toBe(deepseek);
    fireEvent.click(screen.getByTestId("usage-cost"));
    const swatch = (r: HTMLElement) => within(r).queryByTestId("usage-swatch")?.style.background;
    const rows = screen.getAllByTestId("usage-row");
    expect(rows.map(swatch)).toEqual([deepseek, deepseek, claude, undefined]);       // qwen3 has no price, so nothing in the bar to key
  });

  it("folds a fourth model and beyond into Other, in grey", async () => {
    getUsageSummary.mockResolvedValue(summary([row("m-a", 0.4), row("m-b", 0.3), row("m-c", 0.2), row("m-d", 0.06), row("m-e", 0.04)]));
    render(<UsageCard />);
    await waitFor(() => expect(screen.getAllByTestId("usage-cost-seg")).toHaveLength(4));
    const segs = screen.getAllByTestId("usage-cost-seg");
    expect(segs.map((s) => s.getAttribute("title"))).toEqual(
      ["m-a · $0.40 · 40%", "m-b · $0.30 · 30%", "m-c · $0.20 · 20%", "Other models · $0.10 · 10%"]);
    expect(new Set(segs.slice(0, 3).map((s) => s.style.background)).size).toBe(3);
    expect(segs[3].style.background).toBe("var(--muted-foreground)");             // #610 review F5: 3:1 on the light surface
    fireEvent.click(screen.getByTestId("usage-cost"));
    const rows = screen.getAllByTestId("usage-row");
    expect(within(rows[3]).getByTestId("usage-swatch").style.background).toBe("var(--muted-foreground)");
    expect(within(rows[4]).getByTestId("usage-swatch").style.background).toBe("var(--muted-foreground)");
  });

  it("counts priced calls with no model as Other, keyed in grey (#610 review F1)", async () => {
    getUsageSummary.mockResolvedValue(summary([row("m-a", 0.6), row(null, 0.4, 10_000, "answer", "unknown")]));
    render(<UsageCard />);
    await waitFor(() => expect(screen.getAllByTestId("usage-cost-seg")).toHaveLength(2));
    expect(screen.getAllByTestId("usage-cost-seg").map((s) => s.getAttribute("title"))).toEqual(
      ["m-a · $0.60 · 60%", "Other models · $0.40 · 40%"]);
    fireEvent.click(screen.getByTestId("usage-cost"));
    expect(within(screen.getAllByTestId("usage-row")[1]).getByTestId("usage-swatch").style.background).toBe("var(--muted-foreground)");
  });

  it("keeps every model's colour through three ranges whose models clash over a slot (#610 review F1)", async () => {
    const ranges: Record<string, Row[]> = {
      "7d": [row("m-a", 0.5), row("m-b", 0.3), row("m-c", 0.2)],
      "30d": [row("m-a", 0.5), row("m-d", 0.3), row("m-e", 0.2)],                // m-d takes the slot m-b had
      "24h": [row("m-b", 0.5), row("m-d", 0.3), row("m-c", 0.2)],                // m-b and m-d both remember it
    };
    getUsageSummary.mockImplementation(async (range: string) => summary(ranges[range]));
    render(<UsageCard />);
    const colours = () => Object.fromEntries(screen.getAllByTestId("usage-cost-seg")
      .map((s) => [s.getAttribute("title")!.split(" · ")[0], s.style.background]));
    await waitFor(() => expect(Object.keys(colours())).toEqual(["m-a", "m-b", "m-c"]));
    const week = colours();
    fireEvent.click(screen.getByTestId("usage-range-30d"));
    await waitFor(() => expect(Object.keys(colours())).toEqual(["m-a", "m-d", "m-e"]));
    fireEvent.click(screen.getByTestId("usage-range-24h"));
    await waitFor(() => expect(Object.keys(colours())).toEqual(["m-b", "m-d", "m-c"]));
    const day = colours();
    expect(day["m-b"]).toBe(week["m-b"]);
    expect(day["m-c"]).toBe(week["m-c"]);
    expect(new Set(Object.values(day)).size).toBe(3);
  });

  it("tells a model that costs nothing from one with no price: a hollow key, not none (#610 review F2)", async () => {
    getUsageSummary.mockResolvedValue(summary([row("m-a", 0.6), row("free-model", 0, 10_000, "answer", "openrouter"),
      row("local", null, 10_000, "spawn", "ollama")]));
    render(<UsageCard />);
    await waitFor(() => expect(screen.getAllByTestId("usage-cost-seg")).toHaveLength(1));    // $0 draws nothing in the bar
    fireEvent.click(screen.getByTestId("usage-cost"));
    const [, free, local] = screen.getAllByTestId("usage-row");
    expect(within(free).getByTestId("usage-swatch")).toHaveAttribute("data-free");
    expect(within(local).queryByTestId("usage-swatch")).toBeNull();
  });

  it("names the cost tile for a screen reader: the cost, then that it opens by model (#610 review F4)", async () => {
    render(<UsageCard />);
    expect(await screen.findByRole("button", { name: "Cost $0.92, by model", expanded: false })).toBeTruthy();
    expect(screen.getByTestId("usage-cost").querySelector("div")).toBeNull();          // phrasing content only inside a button
  });

  it("keeps a model's colour when the range changes, even when it is no longer the largest", async () => {
    getUsageSummary.mockImplementation(async (range: string) => summary(range === "30d"
      ? [row("deepseek-v4-pro", 2.0), row("claude-sonnet-5-5", 1.0, 10_000, "answer", "anthropic"), row("gpt-5", 0.5, 10_000, "answer", "openai")]
      : WEEK));
    render(<UsageCard />);
    const colours = () => Object.fromEntries(screen.getAllByTestId("usage-cost-seg")
      .map((s) => [s.getAttribute("title")!.split(" · ")[0], s.style.background]));
    await waitFor(() => expect(screen.getAllByTestId("usage-cost-seg")).toHaveLength(2));
    const week = colours();
    fireEvent.click(screen.getByTestId("usage-range-30d"));
    await waitFor(() => expect(screen.getAllByTestId("usage-cost-seg")).toHaveLength(3));
    const month = colours();
    expect(month["deepseek-v4-pro"]).toBe(week["deepseek-v4-pro"]);
    expect(month["claude-sonnet-5-5"]).toBe(week["claude-sonnet-5-5"]);
    expect(new Set(Object.values(month)).size).toBe(3);
  });

  it("is still open after leaving the page and coming back", async () => {
    const first = render(<UsageCard />);
    fireEvent.click(await screen.findByTestId("usage-cost"));
    first.unmount();
    render(<UsageCard />);
    expect(await screen.findByTestId("usage-cost")).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findAllByTestId("usage-row")).toHaveLength(4);
  });
});
