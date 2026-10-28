/** 0.1.55 §13: Memory as one page — to sort, always in view, about you by recent use, rail. */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";

// One `t` for every render, as react-i18next gives: a new one each render would re-create Memory's reload
// and load the page again after every change.
vi.mock("react-i18next", () => {
  const t = (key: string, o?: Record<string, unknown>) => (o && "count" in o ? `${key}:${o.count}`
    : o && "cap" in o ? `${key}:${o.used}/${o.cap}` : key);
  return { useTranslation: () => ({ t, i18n: { resolvedLanguage: "en" } }) };
});
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
import { loadPendingMemory } from "../lib/pendingMemory";
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

describe("待整理 (to sort): what was not remembered directly (INB2)", () => {
  const proposal = (id: number, reason: string, over: Partial<MemoryEntry> = {}) => ({ id, target_id: `e${id}`,
    target_version: 1, candidate: null, reason, entry: entry({ id: `e${id}`, content: `memory ${id}`, status: "proposed", ...over }) });
  const suggestion = { id: 9, kind: "supersede_suspect", table_name: "t", new_id: 1, old_id: 2, reason: "Merge two rules",
    status: "pending", provenance: null, created_at: "2026-10-07T00:00:00Z", resolved_at: null } as const;
  const practice = { id: 5, text: "Rename → use the shell", status: "proposed", source: "detour", situation: "", advice: "",
    polarity: "do", pinned: false, recalled: 0, followed: 0, succeeded: 0, failed: 0, evidence: {}, last_used_at: null,
    created_at: "2026-10-06T00:00:00Z", updated_at: "" } as Lesson;

  it("both sources load with why each waits; one failing hides nothing else; practices are not among them", async () => {
    vi.spyOn(companionApi, "proposals").mockResolvedValue([proposal(1, "external_seen", { sensitivity: "sensitive" })] as never);
    vi.spyOn(api, "listMemoryProposals").mockRejectedValue(new Error("down"));
    vi.spyOn(lessonsApi, "list").mockResolvedValue([practice]);
    const items = await loadPendingMemory(((k: string) => k) as never);
    expect(items.map((i) => [i.key, i.source, i.reason, i.sensitive])).toEqual([["m:1", "memory", "external_seen", true]]);
  });

  it("loads every waiting row, page by page, not only the first page of each source (#475 review)", async () => {
    const proposals = vi.spyOn(companionApi, "proposals").mockImplementation(async (offset = 0) =>
      (offset === 0 ? Array.from({ length: 100 }, (_, i) => proposal(i + 1, "external_seen")) : [proposal(501, "sensitive")]) as never);
    const suggestions = vi.spyOn(api, "listMemoryProposals").mockImplementation(async (opts) =>
      (opts?.offset ? [] : Array.from({ length: 100 }, (_, i) => ({ ...suggestion, id: 1000 + i }))) as never);
    const items = await loadPendingMemory(((k: string) => k) as never);
    expect(items).toHaveLength(201);
    expect(proposals.mock.calls.map((c) => c[0])).toEqual([0, 100]);
    expect(suggestions.mock.calls.map((c) => c[0])).toEqual([{ status: "pending", limit: 100, offset: 0 },
                                                             { status: "pending", limit: 100, offset: 100 }]);
  });

  it("is folded, counts every row, and opened lists them by why they wait; nothing is answered on its own", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([]);
    vi.spyOn(companionApi, "proposals").mockResolvedValue([
      proposal(1, "external_seen"), proposal(2, "sensitive", { sensitivity: "sensitive" }), proposal(3, "confirmation_required"),
      proposal(4, "not_present"), proposal(6, "external_seen", { sensitivity: "sensitive" }),
    ] as unknown as MemoryProposal[]);
    vi.spyOn(api, "listMemoryProposals").mockResolvedValue([suggestion]);
    vi.spyOn(companionApi, "noticedEarlier").mockResolvedValue({ count: 1 });
    vi.spyOn(lessonsApi, "list").mockResolvedValue([practice]);
    const resolve = vi.spyOn(companionApi, "resolveProposal").mockResolvedValue({} as never);
    const apply = vi.spyOn(api, "acceptMemoryProposal").mockResolvedValue({} as never);
    const useAll = vi.spyOn(companionApi, "acceptNoticedEarlier").mockResolvedValue({ accepted: 0 });
    render(<MemoryList />);
    const block = await screen.findByTestId("memory-to-sort");
    const toggle = within(block).getByRole("button", { name: /memoryPage\.toSort/ });
    await waitFor(() => expect(within(toggle).getByTestId("to-sort-count")).toHaveTextContent("6"));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(block).queryAllByTestId(/^pending-memory-/)).toHaveLength(0);
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const groups = within(block).getAllByTestId(/^to-sort-group-/);
    expect(groups.map((group) => group.dataset.testid)).toEqual(["to-sort-group-sensitive", "to-sort-group-external_seen",
      "to-sort-group-not_present", "to-sort-group-curation", "to-sort-group-other"]);
    const rows = (group: HTMLElement) => within(group).getAllByTestId(/^pending-memory-/).map((row) => row.dataset.testid);
    expect(groups.map(rows)).toEqual([["pending-memory-m:2"], ["pending-memory-m:1", "pending-memory-m:6"],
      ["pending-memory-m:4"], ["pending-memory-c:9"], ["pending-memory-m:3"]]);
    expect(within(groups[1]).getByTestId("pending-memory-m:6")).toHaveTextContent("memoryPage.sensitive");
    expect(within(block).getByText("companion.useAll")).toBeInTheDocument();      // "Use all" for what was noticed earlier stays
    // v0.1.64 (INB1): a practice that is not in effect is listed with its reason, not here.
    expect(within(block).queryByTestId("pending-memory-l:5")).toBeNull();
    expect(within(await screen.findByTestId("practices-not-in-effect")).getByTestId("practice-5")).toBeInTheDocument();
    expect(resolve).not.toHaveBeenCalled();
    expect(apply).not.toHaveBeenCalled();
    expect(useAll).not.toHaveBeenCalled();
  });

  it("each row is answered in place: a sensitive one for this Mac only, a suggestion applied, any one dropped", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([]);
    vi.spyOn(companionApi, "proposals").mockResolvedValue([proposal(2, "sensitive", { sensitivity: "sensitive" }),
      proposal(1, "external_seen")] as unknown as MemoryProposal[]);
    vi.spyOn(api, "listMemoryProposals").mockResolvedValue([suggestion]);
    const resolve = vi.spyOn(companionApi, "resolveProposal").mockResolvedValue({} as never);
    const apply = vi.spyOn(api, "acceptMemoryProposal").mockResolvedValue({} as never);
    render(<MemoryList />);
    const block = await screen.findByTestId("memory-to-sort");
    fireEvent.click(within(block).getByRole("button", { name: /memoryPage\.toSort/ }));
    const press = async (row: string, label: string) => {
      const button = within(await within(block).findByTestId(row)).getByText(label);
      await waitFor(() => expect(button).not.toBeDisabled());
      fireEvent.click(button);
    };
    await press("pending-memory-m:2", "pendingMemory.keepLocal");
    // #475 recheck, G4: each row names the version it showed, as the chat line does.
    await waitFor(() => expect(resolve).toHaveBeenCalledWith(2, true, true, false, 1));
    await press("pending-memory-m:1", "pendingMemory.drop");
    await waitFor(() => expect(resolve).toHaveBeenLastCalledWith(1, false, false, false, 1));
    await press("pending-memory-c:9", "pendingMemory.apply");
    await waitFor(() => expect(apply).toHaveBeenCalledWith(9));
    expect(within(block).getByRole("button", { name: /memoryPage\.toSort/ })).toHaveAttribute("aria-expanded", "true");
  });
});

describe("what is always in view", () => {
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
