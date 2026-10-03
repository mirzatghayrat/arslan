/** 0.1.52 S5: the "learned a practice" line, its store frame, Brain's list, the island count, the setting. */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => (opts?.text ? `${key}:${opts.text}` : key),
    i18n: { resolvedLanguage: "en" } }),
}));
vi.mock("../components/EmbeddingSettings", () => ({ default: () => null }));
vi.mock("../components/settings/DeletionManifestExport", () => ({ default: () => null }));
vi.mock("../components/settings/CreateBackupButton", () => ({ default: () => null }));

import LearnedLine from "../components/LearnedLine";
import MemoryList from "../components/companion/MemoryList";
import MemoryDataSection from "../components/settings/MemoryDataSection";
import { lessonsApi, type Lesson } from "../api/lessons";
import { companionApi } from "../api/companion";
import { toUiMessages } from "../api/adapters";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { applyFeed, dismiss, initialState, open } from "../island/islandMachine";
import type { Feed, FeedEvent } from "../island/feed";
import { FIELD_HOMES } from "../components/settings/sectionRegistry";

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
  it("a practice that waits asks: remember or not", async () => {
    const set = vi.spyOn(lessonsApi, "setStatus").mockResolvedValue({} as Lesson);
    render(<LearnedLine id={8} text="x → y" status="proposed" />);
    expect(screen.getByTestId("learned-line")).toHaveTextContent("chat.wantsToLearn:x → y");
    expect(screen.queryByText("chat.learnedUndo")).toBeNull();
    fireEvent.click(screen.getByText("chat.learnedKeep"));
    await waitFor(() => expect(screen.getByText("chat.learnedKept")).toBeInTheDocument());
    expect(set).toHaveBeenCalledWith(8, "active");
    cleanup();
    render(<LearnedLine id={9} text="x → y" status="proposed" />);
    fireEvent.click(screen.getByText("chat.learnedSkip"));
    await waitFor(() => expect(set).toHaveBeenLastCalledWith(9, "archived"));
  });
  it("a frame becomes one line in the thread", () => {
    useArslanStore.setState(initialArslanState());
    useArslanStore.getState().handleFrame({ type: "lesson_learned", lesson: { id: 3, text: "a → b", status: "active" } } as never);
    const items = useArslanStore.getState().items;
    expect(items[items.length - 1]).toMatchObject({ kind: "lesson", content: "a → b", lesson: { id: 3, status: "active" } });
    const [message] = toUiMessages(items.slice(-1));
    expect(message.learned).toEqual({ id: 3, status: "active" });
    expect(message.text).toBe("a → b");
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
  it("lists practices with their source and counts; retired ones fold away", async () => {
    vi.spyOn(lessonsApi, "list").mockResolvedValue([
      lesson({ id: 1, text: "Reminders → use Swift", source: "machine_quirk" }),
      lesson({ id: 2, text: "Reports → tables first", source: "user_correction", status: "proposed" }),
      lesson({ id: 3, text: "Old way", status: "archived" }),
    ]);
    render(<MemoryList />);
    const first = await screen.findByTestId("practice-1");
    expect(first).toHaveTextContent("companion.sourceQuirk");
    expect(first).toHaveTextContent("companion.practiceCounts");
    expect(screen.getByTestId("practice-2")).toHaveTextContent("companion.practiceWaiting");
    expect(screen.queryByTestId("practice-3")).toBeNull();
    fireEvent.click(screen.getByText("companion.practiceRetired"));
    expect(screen.getByTestId("practice-3")).toHaveTextContent("companion.practiceRestore");
  });
  it("use, retire, pin and delete call the API", async () => {
    vi.spyOn(lessonsApi, "list").mockResolvedValue([lesson({ id: 2, status: "proposed" })]);
    const set = vi.spyOn(lessonsApi, "setStatus").mockResolvedValue({} as Lesson);
    const pin = vi.spyOn(lessonsApi, "pin").mockResolvedValue({} as Lesson);
    const remove = vi.spyOn(lessonsApi, "remove").mockResolvedValue({});
    render(<MemoryList />);
    await screen.findByTestId("practice-2");
    fireEvent.click(screen.getByText("companion.practiceUse"));
    await waitFor(() => expect(set).toHaveBeenCalledWith(2, "active"));
    fireEvent.click(await screen.findByText("companion.practiceRetire"));
    await waitFor(() => expect(set).toHaveBeenLastCalledWith(2, "archived"));
    fireEvent.click(await screen.findByText("companion.practicePin"));
    await waitFor(() => expect(pin).toHaveBeenCalledWith(2, true));
    fireEvent.click(await screen.findByText("companion.remove"));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(2));
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
    distillOnSessionEnd: false, onDistillChange: vi.fn(), retentionDays: 30, onRetentionDaysChange: vi.fn() };
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
