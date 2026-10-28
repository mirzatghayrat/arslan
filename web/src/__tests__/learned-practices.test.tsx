/** 0.1.52 S5: the "learned a practice" line, its store frame, Brain's list, the island count, the setting.
 *  v0.1.64 (INB1): nothing waits for an OK. One that is not in effect says why, in the line and in Memory,
 *  and is switched on in Memory after its full text and the reason are shown. */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) =>
    (opts?.text ? `${key}:${opts.text}` : opts?.reason ? `${key}:${opts.reason}` : key),
    i18n: { resolvedLanguage: "en" } }),
}));
vi.mock("../components/EmbeddingSettings", () => ({ default: () => null }));
vi.mock("../components/settings/DeletionManifestExport", () => ({ default: () => null }));
vi.mock("../components/settings/CreateBackupButton", () => ({ default: () => null }));

import LearnedLine from "../components/LearnedLine";
import MemoryList from "../components/companion/MemoryList";
import { ConfirmHost } from "../components/kit";
import MemoryDataSection from "../components/settings/MemoryDataSection";
import { lessonsApi, type Lesson } from "../api/lessons";
import { companionApi } from "../api/companion";
import { toUiMessages } from "../api/adapters";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { applyFeed, dismiss, initialState, open } from "../island/islandMachine";
import type { Feed, FeedEvent } from "../island/feed";
import { FIELD_HOMES } from "../components/settings/sectionRegistry";
import { OPEN_SECTION_EVENT } from "../lib/sections";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the learned line in the chat", () => {
  it("undo retires the practice", async () => {
    const set = vi.spyOn(lessonsApi, "setStatus").mockResolvedValue({} as Lesson);
    render(<LearnedLine id={7} text="Reminders → use Swift" status="active" />);
    expect(screen.getByTestId("learned-line")).toHaveTextContent("chat.learned:Reminders → use Swift");
    fireEvent.click(screen.getByText("chat.learnedUndo"));
    await waitFor(() => expect(screen.getByText("chat.learnedUndone")).toBeInTheDocument());
    expect(set).toHaveBeenCalledWith(7, "archived");
  });
  it("one that is not in effect says why and points to Memory; it asks nothing and changes nothing", () => {
    const set = vi.spyOn(lessonsApi, "setStatus").mockResolvedValue({} as Lesson);
    const opened: unknown[] = [];
    const listen = (event: Event) => opened.push((event as CustomEvent).detail);
    window.addEventListener(OPEN_SECTION_EVENT, listen);
    try {
      render(<LearnedLine id={8} text="x → y" status="proposed" notInEffect="conflicts" />);
      expect(screen.getByTestId("learned-line")).toHaveTextContent("chat.learnedNotInEffect:companion.why_conflicts");
      expect(screen.queryByText("chat.learnedUndo")).toBeNull();
      fireEvent.click(screen.getByText("chat.learnedSeeInMemory"));
      expect(opened).toEqual(["brain"]);
      expect(set).not.toHaveBeenCalled();
    } finally { window.removeEventListener(OPEN_SECTION_EVENT, listen); }
  });
  it("with no reason given, the line says the safe one", () => {
    render(<LearnedLine id={9} text="x → y" status="proposed" />);
    expect(screen.getByTestId("learned-line")).toHaveTextContent("chat.learnedNotInEffect:companion.why_outside_content");
  });
  it("a frame becomes one line in the thread, with its reason", () => {
    useArslanStore.setState(initialArslanState());
    useArslanStore.getState().handleFrame({ type: "lesson_learned", lesson: { id: 3, text: "a → b", status: "active", not_in_effect: null } } as never);
    useArslanStore.getState().handleFrame({ type: "lesson_learned", lesson: { id: 4, text: "c → d", status: "proposed", not_in_effect: "setting_off" } } as never);
    const items = useArslanStore.getState().items;
    expect(items[items.length - 2]).toMatchObject({ kind: "lesson", content: "a → b", lesson: { id: 3, status: "active" } });
    const [active, waiting] = toUiMessages(items.slice(-2));
    expect(active.learned).toEqual({ id: 3, status: "active", notInEffect: null });
    expect(active.text).toBe("a → b");
    expect(waiting.learned).toEqual({ id: 4, status: "proposed", notInEffect: "setting_off" });
  });
});

describe("Brain › learned practices", () => {
  const lesson = (over: Partial<Lesson>): Lesson => ({ id: 1, situation: "s", advice: "a", polarity: "do", source: "detour",
    status: "active", pinned: false, text: "s → a", recalled: 3, followed: 2, succeeded: 2, failed: 0, evidence: {},
    last_used_at: null, created_at: "", updated_at: "", ...over });
  beforeEach(() => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([]);
    vi.spyOn(companionApi, "proposals").mockResolvedValue([]);
    vi.spyOn(companionApi, "projects").mockResolvedValue([]);
    vi.spyOn(companionApi, "noticedEarlier").mockResolvedValue({ count: 0 });
  });
  it("lists practices by state, each one not in use with its reason; retired ones fold away", async () => {
    vi.spyOn(lessonsApi, "list").mockResolvedValue([
      lesson({ id: 1, text: "Reminders → use Swift", source: "machine_quirk" }),
      lesson({ id: 2, text: "Reports → tables first", source: "user_correction", status: "proposed",
        not_in_effect: "setting_off", evidence: { not_in_effect: "setting_off" } }),
      lesson({ id: 3, text: "Old way", status: "archived" }),
      lesson({ id: 5, text: "Before v0.1.64", status: "proposed", not_in_effect: "outside_content", evidence: {} }),
      lesson({ id: 6, text: "Keeps failing", status: "stale", not_in_effect: "failed_repeatedly",
        evidence: { not_in_effect: "failed_repeatedly" } }),
    ]);
    render(<MemoryList />);
    const first = await screen.findByTestId("practice-1");
    expect(first).toHaveTextContent("companion.sourceQuirk");
    expect(first).toHaveTextContent("companion.practiceCounts");
    expect(first).not.toHaveTextContent("companion.whyShort_");
    // Nothing about practices waits with the rest for an OK.
    expect(screen.queryByTestId("pending-memory-l:2")).toBeNull();
    const notInEffect = screen.getByTestId("practices-not-in-effect");
    expect(within(notInEffect).getByTestId("practice-2")).toHaveTextContent("companion.whyShort_setting_off");
    // One learned before v0.1.64 has no reason written: the page says so, not a guess.
    expect(within(notInEffect).getByTestId("practice-5")).toHaveTextContent("companion.whyShort_legacy");
    expect(within(screen.getByTestId("practices-stopped")).getByTestId("practice-6"))
      .toHaveTextContent("companion.whyShort_failed_repeatedly");
    expect(screen.queryByTestId("practice-3")).toBeNull();
    fireEvent.click(screen.getByText("companion.practiceRetired"));
    expect(screen.getByTestId("practice-3")).toHaveTextContent("companion.practiceRestore");
  });
  it("one not in effect is switched on only after its full text and reason are shown", async () => {
    vi.spyOn(lessonsApi, "list").mockResolvedValue([
      lesson({ id: 4, text: "Reports → lists first", situation: "Reports", advice: "lists first" }),
      lesson({ id: 2, status: "proposed", text: "Reports → tables first", situation: "Reports", advice: "tables first",
        not_in_effect: "conflicts", evidence: { not_in_effect: "conflicts", conflicts_with: 4 } }),
    ]);
    const set = vi.spyOn(lessonsApi, "setStatus").mockResolvedValue({} as Lesson);
    render(<><MemoryList /><ConfirmHost /></>);
    const row = await screen.findByTestId("practice-2");
    expect(within(row).queryByText("companion.practicePin")).toBeNull();
    fireEvent.click(within(row).getByText("companion.practiceViewAndTurnOn"));
    const sheet = await screen.findByTestId("practice-open-sheet");
    expect(sheet).toHaveTextContent("tables first");
    expect(sheet).toHaveTextContent("companion.practiceWhyNot:companion.why_conflicts");
    expect(sheet).toHaveTextContent("companion.whyDetail_conflicts");
    expect(sheet).toHaveTextContent("companion.practiceRival:Reports → lists first");
    expect(set).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("companion.practiceNotNow"));
    await waitFor(() => expect(screen.queryByTestId("practice-open-sheet")).toBeNull());
    expect(set).not.toHaveBeenCalled();
    fireEvent.click(within(await screen.findByTestId("practice-2")).getByText("companion.practiceViewAndTurnOn"));
    await screen.findByTestId("practice-open-sheet");
    fireEvent.click(screen.getByTestId("confirm-action"));
    await waitFor(() => expect(set).toHaveBeenCalledWith(2, "active"));
  });
  it("retire, pin and delete call the API; delete asks first", async () => {
    vi.spyOn(lessonsApi, "list").mockResolvedValue([lesson({ id: 4, text: "in use" })]);
    const set = vi.spyOn(lessonsApi, "setStatus").mockResolvedValue({} as Lesson);
    const pin = vi.spyOn(lessonsApi, "pin").mockResolvedValue({} as Lesson);
    const remove = vi.spyOn(lessonsApi, "remove").mockResolvedValue({});
    render(<><MemoryList /><ConfirmHost /></>);
    await screen.findByTestId("practice-4");
    fireEvent.click(await screen.findByText("companion.practiceRetire"));
    await waitFor(() => expect(set).toHaveBeenLastCalledWith(4, "archived"));
    fireEvent.click(await screen.findByText("companion.practicePin"));
    await waitFor(() => expect(pin).toHaveBeenCalledWith(4, true));
    fireEvent.click(await screen.findByText("companion.remove"));
    expect((await screen.findAllByText("memoryPage.deletePracticeTitle")).length).toBeGreaterThan(0);
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("confirm-action"));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(4));
  });
  it("no practices, no panel", async () => {
    vi.spyOn(lessonsApi, "list").mockResolvedValue([]);
    render(<MemoryList />);
    await waitFor(() => expect(companionApi.memories).toHaveBeenCalled());
    expect(screen.queryByTestId("learned-practices")).toBeNull();
  });
});

describe("island: +1 practice", () => {
  const ev = (id: number, kind = "lesson_learned"): FeedEvent => ({ id, kind, conversation_id: "c1", outcome: null,
    task_id: null, at: 1, title: null, summary: "a → b", work: null } as FeedEvent);
  const feed = (cursor: number, events: FeedEvent[] = []): Feed => ({ cursor, awaiting: 0, awaiting_conversations: [],
    active: [], events, enabled: true });
  it("counts quietly, never as a card, and clears when you close or open", () => {
    let s = applyFeed(initialState(), feed(5, [ev(5)]), 0);           // history is not replayed
    expect(s.learned).toBe(0);
    s = applyFeed(s, feed(7, [ev(6), ev(7)]), 1);
    expect(s.learned).toBe(2);
    expect(s.current).toBeNull() ;
    expect(s.queue).toEqual([]);
    expect(dismiss(s, 2).learned).toBe(0);
    expect(open(s, 2).learned).toBe(0);
  });
});

describe("Settings › Memory › learned practices take effect", () => {
  const base = { providerConfigs: [], embeddingConfigId: "", onEmbeddingConfigIdChange: vi.fn(),
    retentionDays: 30, onRetentionDaysChange: vi.fn() };
  it("is on unless turned off and reports changes", () => {
    const onChange = vi.fn();
    const { rerender } = render(<MemoryDataSection {...base} onLearnedPracticesChange={onChange} />);
    const toggle = screen.getByTestId("settings-learned-practices") as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(false);
    rerender(<MemoryDataSection {...base} learnedPracticesTakeEffect={false} onLearnedPracticesChange={onChange} />);
    expect((screen.getByTestId("settings-learned-practices") as HTMLInputElement).checked).toBe(false);
    expect(FIELD_HOMES["memory.learned_practices"]).toBe("memory");
  });
});
