/** Rename a conversation from the sidebar or its header, and the header that stays tidy beside the panel (v0.1.64).
 *
 * Entry points: right-click a row → Rename, double-click its title, ⋯ → Rename, F2 on the row, and the header's title.
 * Editing: Enter saves, Esc cancels, leaving the field saves; an empty or unchanged name keeps the old one.
 * The header's chips give way by its own width (Tailwind container variants); jsdom applies no CSS, so the
 * steps are pinned by their classes and the ⋯ menu by what it lists. */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, params?: Record<string, unknown>) => (params?.title ? `${key}:${params.title}` : key),
    i18n: { language: "en", resolvedLanguage: "en" } }),
}));
vi.mock("../api/client", () => ({ api: { listConversations: vi.fn(async () => []) }, request: vi.fn() }));

import Sidebar from "../components/Sidebar";
import ConversationHeader, { HDR_LABEL, HDR_RUN, HDR_SECONDARY } from "../components/conversation/ConversationHeader";
import ConversationControls from "../components/companion/ConversationControls";
import { companionApi, type ConversationContext } from "../api/companion";
import { seedTitledThreadIds, shouldAutoTitle } from "../lib/autoTitle";
import { applyGeneratedTitle, renameThread } from "../lib/threadTitles";
import { persistThreads, restoreThreads } from "../lib/sessionPersistence";
import type { Message } from "../types";

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

const threads = [{ id: "a", title: "Photo backup duplicates" }, { id: "b", title: "Weekly report" }];
function renderSidebar() {
  const onRenameThread = vi.fn();
  const onSelectThread = vi.fn();
  render(<Sidebar threads={threads} activeThreadId="a" onSelectThread={onSelectThread} onAddThread={() => {}}
    activeSection="arslan" onChangeSection={() => {}} onArchiveThread={vi.fn()} onUnarchiveThread={vi.fn()}
    onDeleteThread={vi.fn()} backendStatus="online" onRenameThread={onRenameThread} />);
  return { onRenameThread, onSelectThread, row: () => document.getElementById("active-thread-btn-b")! };
}
const input = () => screen.getByRole("textbox", { name: "sidebar.renameLabel" }) as HTMLInputElement;

describe("rename from the sidebar", () => {
  it("right-click on a row opens its menu with Rename, which edits the row in place", () => {
    const { onRenameThread, row } = renderSidebar();
    fireEvent.contextMenu(row());
    fireEvent.click(screen.getByTestId("thread-rename"));
    expect(input().value).toBe("Weekly report");
    expect(within(row()).getByRole("textbox")).toBe(input());     // in the row, not somewhere else
    fireEvent.change(input(), { target: { value: "Week 2 report" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onRenameThread).toHaveBeenCalledWith("b", "Week 2 report");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("double-clicking the title edits it", () => {
    const { onRenameThread } = renderSidebar();
    fireEvent.doubleClick(screen.getByText("Weekly report"));
    fireEvent.change(input(), { target: { value: "  Renamed  " } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onRenameThread).toHaveBeenCalledWith("b", "Renamed");   // trimmed
  });

  it("⋯ → Rename edits it", () => {
    const { onRenameThread, row } = renderSidebar();
    fireEvent.click(within(row()).getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByText("sidebar.rename"));
    fireEvent.change(input(), { target: { value: "From the menu" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onRenameThread).toHaveBeenCalledWith("b", "From the menu");
  });

  it("F2 on a focused row edits it, and Enter puts focus back on the row", () => {
    const { onRenameThread, row } = renderSidebar();
    row().focus();
    fireEvent.keyDown(row(), { key: "F2" });
    fireEvent.change(input(), { target: { value: "By keyboard" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onRenameThread).toHaveBeenCalledWith("b", "By keyboard");
    expect(document.activeElement).toBe(row());
  });

  it("Esc cancels: the typed name is dropped", () => {
    const { onRenameThread } = renderSidebar();
    fireEvent.doubleClick(screen.getByText("Weekly report"));
    fireEvent.change(input(), { target: { value: "Not this" } });
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(onRenameThread).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("Weekly report")).toBeInTheDocument();
  });

  it("leaving the field saves", () => {
    const { onRenameThread } = renderSidebar();
    fireEvent.doubleClick(screen.getByText("Weekly report"));
    fireEvent.change(input(), { target: { value: "Saved on blur" } });
    fireEvent.blur(input());
    expect(onRenameThread).toHaveBeenCalledWith("b", "Saved on blur");
    expect(onRenameThread).toHaveBeenCalledTimes(1);
  });

  it("an empty or unchanged name keeps the old one", () => {
    const { onRenameThread } = renderSidebar();
    fireEvent.doubleClick(screen.getByText("Weekly report"));
    fireEvent.change(input(), { target: { value: "   " } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.doubleClick(screen.getByText("Weekly report"));
    fireEvent.keyDown(input(), { key: "Enter" });                  // unchanged
    expect(onRenameThread).not.toHaveBeenCalled();
  });

  it("typing in the field does not open or drag the row", () => {
    const { onSelectThread, row } = renderSidebar();
    fireEvent.doubleClick(screen.getByText("Weekly report"));
    onSelectThread.mockClear();
    fireEvent.click(input());
    fireEvent.keyDown(input(), { key: " " });
    expect(onSelectThread).not.toHaveBeenCalled();
    expect(row()).not.toHaveAttribute("draggable");
  });
});

describe("rename from the header", () => {
  it("clicking the title edits it; Enter saves, Esc cancels", () => {
    const onRename = vi.fn();
    render(<ConversationHeader title="Release checklist" onRename={onRename}><span /></ConversationHeader>);
    const title = screen.getByTestId("header-title");
    expect(title).toHaveAttribute("title", "sidebar.renameHint:Release checklist");
    fireEvent.click(title);
    fireEvent.change(input(), { target: { value: "Release checks" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith("Release checks");
    fireEvent.click(screen.getByTestId("header-title"));
    fireEvent.change(input(), { target: { value: "Dropped" } });
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(onRename).toHaveBeenCalledTimes(1);
  });

  it("a conversation that cannot be renamed shows its title as text", () => {
    render(<ConversationHeader title="Temporary"><span /></ConversationHeader>);
    expect(screen.getByTestId("header-title").tagName).toBe("SPAN");
  });
});

describe("the header by its own width", () => {
  const chips = (onProject = vi.fn(), onRun = vi.fn()) => <>
    <button type="button" aria-label="settings · arslan" onClick={onProject}>
      <span data-hdr-chip="secondary" title="Project arslan" className={HDR_SECONDARY}><span className={HDR_LABEL}>Project arslan</span></span>
    </button>
    <button type="button" aria-label="tasks.taskStatus · tasks.failed" className={HDR_RUN} onClick={onRun}>
      <span data-hdr-chip="secondary" title="Task status · Stopped with an error" className={HDR_SECONDARY} />
      <span data-hdr-chip="run" title="Stopped with an error" />
    </button>
  </>;

  it("is a named inline-size container; the title comes first, one line, at least 4em", () => {
    render(<ConversationHeader title="T" onRename={vi.fn()}>{chips()}</ConversationHeader>);
    const header = screen.getByTestId("conversation-header");
    expect(header.className).toContain("@container/hdr");
    const title = screen.getByTestId("header-title");
    expect(title.className).toMatch(/\btruncate\b/);
    expect(title.className).toContain("min-w-[4em]");
    expect(header.querySelector("button")).toBe(title);
  });

  it("the steps: labels at 560, secondary chips and ⋯ at 400, the run state at 300", () => {
    expect(HDR_LABEL).toBe("@max-[560px]/hdr:hidden");
    expect(HDR_SECONDARY).toBe("@max-[400px]/hdr:hidden");
    expect(HDR_RUN).toBe("@max-[300px]/hdr:hidden");
    render(<ConversationHeader title="T" onRename={vi.fn()}>{chips()}</ConversationHeader>);
    expect(screen.getByTestId("header-more-wrap").className).toMatch(/(^| )hidden( |$)/);
    expect(screen.getByTestId("header-more-wrap").className).toContain("@max-[400px]/hdr:block");
  });

  it("⋯ lists what is hidden, the run state only below 300, and an item stands in for its chip", () => {
    const onProject = vi.fn();
    const onRun = vi.fn();
    render(<ConversationHeader title="T" onRename={vi.fn()}>{chips(onProject, onRun)}</ConversationHeader>);
    const more = screen.getByRole("button", { name: "sidebar.headerMore" });
    expect(more).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    const items = within(screen.getByRole("menu")).getAllByRole("menuitem");
    expect(items.map(item => item.textContent)).toEqual(["Project arslan", "Task status · Stopped with an error", "Stopped with an error"]);
    expect(items.map(item => item.className.split(" ").slice(0, 2).join(" "))).toEqual(["flex w-full", "flex w-full", "hidden @max-[300px]/hdr:flex"]);
    fireEvent.click(items[0]);
    expect(onProject).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(more);
    fireEvent.click(within(screen.getByRole("menu")).getAllByRole("menuitem")[2]);
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("the project chip: icon + label that hides at 560, the full text as its tooltip and accessible name", async () => {
    const context: ConversationContext = { conversation_id: "c", version: 0, project_id: "p1", no_memory: true,
      no_learning: false, temporary: false, cloud_memory_allowed: false, allow_sensitive: false };
    vi.spyOn(companionApi, "context").mockResolvedValue(context);
    vi.spyOn(companionApi, "projects").mockResolvedValue([{ id: "p1", name: "arslan" } as never]);
    render(<ConversationControls compact conversationId="c" running={false} empty onChanged={() => {}} />);
    const button = await screen.findByRole("button", { name: "companion.conversationSettings · arslan · companion.noMemory" });
    await waitFor(() => expect(button).toBeEnabled());
    const [project, flag] = Array.from(button.querySelectorAll<HTMLElement>("[data-hdr-chip]"));
    expect(project).toHaveAttribute("title", "arslan");
    expect(project.className).toContain("whitespace-nowrap");
    expect(project.className).toContain(HDR_SECONDARY);
    expect(project.querySelector("svg")).not.toBeNull();
    expect(within(project).getByText("arslan").className).toContain(HDR_LABEL);
    expect(flag).toHaveAttribute("title", "companion.noMemory");
    await act(async () => { fireEvent.click(project); });
    expect(screen.getByRole("dialog")).toBeInTheDocument();          // a chip is the settings button
  });
});

describe("autoTitle never renames what the user named", () => {
  const history: Message[] = [
    { id: "u", sender: "user", senderName: "User", senderAvatar: "", text: "hi", timestamp: "" },
    { id: "a", sender: "arslan", senderName: "Arslan", senderAvatar: "", text: "hello", timestamp: "" },
  ];

  it("a rename marks the thread userTitled and a later generated title does not land", () => {
    const renamed = renameThread([{ id: "t", title: "New Session", defaultTitle: true }], "t", "Renamed by the user");
    expect(renamed[0]).toMatchObject({ title: "Renamed by the user", userTitled: true, defaultTitle: undefined });
    expect(applyGeneratedTitle(renamed, "t", "Generated")[0].title).toBe("Renamed by the user");
    expect(applyGeneratedTitle([{ id: "t", title: "hi" }], "t", "Generated")[0].title).toBe("Generated");   // not renamed: lands
    expect(renameThread(renamed, "t", "   ")).toBe(renamed);                                              // empty: nothing
  });

  it("a placeholder-looking name the user typed is still titled after a reload", () => {
    // Discriminating: by its title alone "New Session" is a placeholder, so without userTitled the first exchange
    // after a reload would be auto-titled over the user's own name.
    persistThreads(renameThread([{ id: "t", title: "x", history: [] }], "t", "New Session"), "t");
    const restored = restoreThreads().threads;
    expect(restored[0]).toMatchObject({ title: "New Session", userTitled: true });
    expect(restored[0].defaultTitle).toBeUndefined();
    expect(shouldAutoTitle({ title: "New Session", history })).toBe(true);   // the exchange alone would title it
    expect(seedTitledThreadIds(restored).has("t")).toBe(true);
    expect(seedTitledThreadIds([{ id: "t", title: "New Session" }]).has("t")).toBe(false);
  });
});
