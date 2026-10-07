/** 0.1.55 §13: Memory as one page — waiting, always in view, about you by recent use, rail. */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, o?: Record<string, unknown>) => (o && "count" in o ? `${key}:${o.count}`
      : o && "cap" in o ? `${key}:${o.used}/${o.cap}` : key),
    i18n: { resolvedLanguage: "en" },
  }),
}));
vi.mock("../components/brain/BrainSection", () => ({
  default: (props: { page?: boolean }) => <div data-testid="graph" data-page={String(!!props.page)} />,
}));
vi.mock("../components/companion/Materials", () => ({
  default: (props: { mode?: string }) => <div data-testid="materials" data-mode={props.mode} />,
}));

import MemoryList, { byRecentUse } from "../components/companion/MemoryList";
import MemorySection from "../components/companion/MemorySection";
import { ConfirmHost } from "../components/kit";
import { api } from "../api/client";
import { companionApi, type MemoryEntry, type MemoryProposal, type MemoryStats } from "../api/companion";
import { lessonsApi, type Lesson } from "../api/lessons";
import { OPEN_SECTION_EVENT, readOpenSection } from "../lib/sections";
import { resolveSection } from "../components/settings/sectionRegistry";
import { memoryPageMessages } from "../locales/memoryPage";
import BrainNav from "../components/brain/BrainNav";

const entry = (over: Partial<MemoryEntry>): MemoryEntry => ({
  id: "x", content: "x", kind: "preference", status: "active", version: 1, revision_id: "r",
  scope: { kind: "global", id: null }, sensitivity: "normal", use_policy: "cloud_allowed", topic: null,
  confirmed_at: null, valid_from: null, review_at: null, expires_at: null, created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z", sources: [], uses_this_week: 0, last_used_at: null, ...over,
} as MemoryEntry);

const stats = (over: Partial<MemoryStats> = {}): MemoryStats => ({
  days: 7, retrievals: 23, conversations: 9, new_entries: 4, user_edits: 2,
  core: { about_you: { used: 412, cap: 1500, entries: 1, left_out: 2 }, notes: { used: 0, cap: 2500, entries: 0, left_out: 0 } },
  remember_in_conversations: true, materials: { count: 14, latest: "spec.md" }, notes: { count: 6, latest: null }, ...over,
});

beforeEach(() => {
  vi.spyOn(companionApi, "projects").mockResolvedValue([{ id: "p1", name: "Game", kind: "general", summary: "", workspace_ref: null,
    collection_ids: [], app_binding: null, status: "active", version: 1, updated_at: "" }]);
  vi.spyOn(companionApi, "proposals").mockResolvedValue([]);
  vi.spyOn(companionApi, "noticedEarlier").mockResolvedValue({ count: 0 });
  vi.spyOn(companionApi, "memoryStats").mockResolvedValue(stats());
  vi.spyOn(api, "listMemoryProposals").mockResolvedValue([]);
  vi.spyOn(api, "embeddingStatus").mockResolvedValue({ embedded: 10, pending: 0, total: 10 } as never);
  vi.spyOn(lessonsApi, "list").mockResolvedValue([]);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("about you", () => {
  it("orders by most recent use, then newest edit for the never-used", () => {
    const rows = [
      entry({ id: "never-old", updated_at: "2026-09-01T00:00:00Z" }),
      entry({ id: "used-earlier", last_used_at: "2026-10-07T08:00:00Z" }),
      entry({ id: "never-new", updated_at: "2026-10-05T00:00:00Z" }),
      entry({ id: "used-latest", last_used_at: "2026-10-08T09:00:00Z" }),
    ];
    expect(rows.sort(byRecentUse).map(r => r.id)).toEqual(["used-latest", "used-earlier", "never-new", "never-old"]);
  });

  it("shows how often each was used this week, and the paused ones after the active", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([
      entry({ id: "a", content: "Answers first", uses_this_week: 9, last_used_at: "2026-10-08T00:00:00Z" }),
      entry({ id: "b", content: "Friday review", confirmation_kind: "auto_noticed", use_policy: "local_only" }),
      entry({ id: "c", content: "Old habit", status: "paused" }),
    ]);
    render(<MemoryList />);
    expect(await screen.findByTestId("memory-uses-a")).toHaveTextContent("memoryPage.usedTimes:9");
    expect(screen.getByTestId("memory-uses-b")).toHaveTextContent("memoryPage.notUsed");
    const b = screen.getByTestId("memory-b");
    expect(b).toHaveTextContent("memoryPage.origin_auto_noticed");
    expect(b).toHaveTextContent("memoryPage.localOnly");
    expect(screen.getByTestId("memory-c")).toHaveTextContent("memoryPage.paused");
    const order = [...screen.getByTestId("memory-about").querySelectorAll("[data-testid='memory-a'],[data-testid='memory-b'],[data-testid='memory-c']")]
      .map(el => el.getAttribute("data-testid"));
    expect(order).toEqual(["memory-a", "memory-b", "memory-c"]);
  });

  it("filters by scope", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([
      entry({ id: "g", content: "Everywhere fact" }),
      entry({ id: "p", content: "Game fact", scope: { kind: "project", id: "p1" } }),
    ]);
    render(<MemoryList />);
    await screen.findByText("Game fact");
    fireEvent.change(screen.getByTestId("memory-scope"), { target: { value: "project:p1" } });
    expect(screen.queryByText("Everywhere fact")).toBeNull();
    expect(screen.getByText("Game fact")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("memory-scope"), { target: { value: "global" } });
    expect(screen.queryByText("Game fact")).toBeNull();
  });

  it("delete asks first; cancelling deletes nothing", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([entry({ id: "a", content: "Answers first" })]);
    const del = vi.spyOn(companionApi, "deleteMemory").mockResolvedValue({} as never);
    render(<><MemoryList /><ConfirmHost /></>);
    const row = await screen.findByTestId("memory-a");
    fireEvent.click(within(row).getByText("companion.remove"));
    expect((await screen.findAllByText("memoryPage.deleteTitle")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId("confirm-cancel"));
    await waitFor(() => expect(screen.queryAllByText("memoryPage.deleteTitle")).toHaveLength(0));
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(within(row).getByText("companion.remove"));
    fireEvent.click(await screen.findByTestId("confirm-action"));
    await waitFor(() => expect(del).toHaveBeenCalledTimes(1));
    expect(del.mock.calls[0][0].id).toBe("a");
  });
});

describe("what waits, and what is always in view", () => {
  it("merges the three pending sources into one block, each answerable in place", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([]);
    vi.spyOn(companionApi, "proposals").mockResolvedValue([{ id: 7, target_id: "e", target_version: 1, candidate: null, reason: "",
      entry: entry({ id: "e", content: "Blood pressure note", status: "proposed", sensitivity: "sensitive" }) }] as unknown as MemoryProposal[]);
    vi.spyOn(api, "listMemoryProposals").mockResolvedValue([{ id: 3, kind: "supersede_suspect", table_name: "t", new_id: 1, old_id: 2,
      reason: "Merge two rules", status: "pending", provenance: null, created_at: "2026-10-07T00:00:00Z", resolved_at: null }]);
    vi.spyOn(lessonsApi, "list").mockResolvedValue([{ id: 5, text: "Rename → use the shell", status: "proposed", source: "detour",
      situation: "", advice: "", polarity: "do", pinned: false, recalled: 0, followed: 0, succeeded: 0, failed: 0, evidence: {},
      last_used_at: null, created_at: "2026-10-06T00:00:00Z", updated_at: "" } as Lesson]);
    const resolve = vi.spyOn(companionApi, "resolveProposal").mockResolvedValue({} as never);
    render(<MemoryList />);
    const block = await screen.findByTestId("memory-waiting");
    await waitFor(() => expect(within(block).getAllByTestId(/^pending-memory-/)).toHaveLength(3));
    const sensitive = within(block).getByTestId("pending-memory-m:7");
    expect(sensitive).toHaveTextContent("memoryPage.sensitive");
    // A sensitive one is kept for local models only: acknowledged, not for the cloud.
    fireEvent.click(within(sensitive).getByText("pendingMemory.keepLocal"));
    await waitFor(() => expect(resolve).toHaveBeenCalledWith(7, true, true, false));
  });

  it("shows the server's budgets, and says what did not fit", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([entry({ id: "a", content: "Short replies", core: "about_you" })]);
    render(<MemoryList />);
    const card = await screen.findByTestId("in-view-about_you");
    await waitFor(() => expect(card).toHaveTextContent("memoryPage.inViewChars:412/1500"));
    expect(card).toHaveTextContent("memoryPage.inViewLeftOut:2");
    expect(screen.getByTestId("in-view-notes")).toHaveTextContent("memoryPage.inViewEmpty");
  });
});

describe("the rail", () => {
  it("shows this week, and who can use memory follows the remember-me setting", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([]);
    vi.spyOn(companionApi, "memoryStats").mockResolvedValue(stats({ remember_in_conversations: false }));
    render(<MemoryList />);
    const week = await screen.findByTestId("memory-week");
    expect(week).toHaveTextContent("memoryPage.weekRecalled:23");
    expect(week).toHaveTextContent("memoryPage.weekConversations:9");
    expect(week).toHaveTextContent("memoryPage.weekEdits:2");
    expect(screen.getByTestId("memory-who")).toHaveTextContent("memoryPage.whoCloudOff");
    expect(await screen.findByTestId("memory-index-line")).toHaveTextContent("memoryPage.indexOk");
  });

  it("opens Settings at Memory & privacy", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([]);
    const seen: unknown[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(OPEN_SECTION_EVENT, on);
    render(<MemoryList />);
    fireEvent.click(await screen.findByText(/memoryPage\.whoFoot/));
    window.removeEventListener(OPEN_SECTION_EVENT, on);
    expect(seen).toEqual([{ section: "settings", sub: "memory" }]);
  });
});

describe("the page", () => {
  it("Add › Remember something opens the editor once, even from the graph", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([]);
    localStorage.setItem("arslan.memory.view", "graph");
    render(<MemorySection />);
    expect(screen.getByTestId("graph")).toHaveAttribute("data-page", "true");
    fireEvent.click(screen.getByTestId("memory-add"));
    fireEvent.click(screen.getByText("memoryPage.addMemory"));
    expect(await screen.findByText("companion.addMemory")).toBeInTheDocument();
    // Close it, go to the graph and back: it does not reopen by itself.
    fireEvent.click(screen.getByTestId("memory-view-graph"));
    fireEvent.click(screen.getByTestId("memory-view-list"));
    await screen.findByTestId("memory-rail");
    expect(screen.queryByText("companion.addMemory")).toBeNull();
    localStorage.clear();
  });

  it("feed and note open the materials sub-page in that mode, with a way back", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([]);
    render(<MemorySection />);
    fireEvent.click(await screen.findByText("memoryPage.feed"));
    expect(screen.getByTestId("materials")).toHaveAttribute("data-mode", "feed");
    fireEvent.click(screen.getByTestId("memory-back"));
    fireEvent.click(screen.getByTestId("memory-add"));
    fireEvent.click(screen.getByText("memoryPage.addNote"));
    expect(screen.getByTestId("materials")).toHaveAttribute("data-mode", "note");
  });
});

describe("opening a part of a page", () => {
  it("reads a plain page, a page with a part, and refuses unknown pages", () => {
    expect(readOpenSection("brain")).toEqual({ section: "brain" });
    expect(readOpenSection({ section: "settings", sub: "memory" })).toEqual({ section: "settings", sub: "memory" });
    expect(readOpenSection({ section: "nowhere", sub: "memory" })).toBeNull();
    expect(readOpenSection(42)).toBeNull();
    // App hands the part to Settings through the same resolver as old deep links.
    expect(resolveSection(readOpenSection({ section: "settings", sub: "memory" })!.sub)).toBe("memory");
  });
});

describe("memory page strings", () => {
  it("has the same nonempty keys and placeholders in all six languages", () => {
    const keys = Object.keys(memoryPageMessages.en).sort();
    expect(Object.keys(memoryPageMessages)).toHaveLength(6);
    for (const messages of Object.values(memoryPageMessages)) {
      expect(Object.keys(messages).sort()).toEqual(keys);
      for (const key of keys) {
        const text = messages[key as keyof typeof messages];
        expect(text.trim()).not.toBe("");
        expect((text.match(/\{\{[^}]+\}\}/g) ?? []).sort())
          .toEqual((memoryPageMessages.en[key as keyof typeof messages].match(/\{\{[^}]+\}\}/g) ?? []).sort());
      }
    }
  });
});

describe("the graph's floating card", () => {
  const props = { branches: [{ kind: "profile", children: [] }], litId: null, onHover: () => {}, onPick: () => {},
    onChanged: () => {}, onTagFilter: () => {}, activeTag: null, onClearTag: () => {}, showTags: true, onToggleTags: () => {} } as unknown as Parameters<typeof BrainNav>[0];
  it("browses and filters only: no feed box, no index strip (they live in Add and the rail)", () => {
    render(<BrainNav {...props} floating />);
    expect(screen.getByTestId("brain-nav")).toHaveClass("brain-nav--floating");
    expect(screen.queryByTestId("feed-image-disclosure")).toBeNull();
    expect(screen.queryByText("brain.index_health")).toBeNull();
    cleanup();
    render(<BrainNav {...props} />);
    expect(screen.getByTestId("feed-image-disclosure")).toBeInTheDocument();
  });
});
