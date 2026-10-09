/**
 * 0.1.58 §4 and §5: project conversations live under their project in the sidebar (and can be
 * moved in and out), and a level is cleared early only after saying what happens to what is left.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));

import Sidebar, { PROJECT_CHATS, SIDEBAR_PROJECTS } from "../components/Sidebar";
import ThreadRowMenu from "../components/ThreadRowMenu";
import ProjectPage from "../components/projects/ProjectPage";
import ProjectsSection from "../components/companion/ProjectsSection";
import { ConfirmHost, ToastHost } from "../components/kit";
import { companionApi, type Project } from "../api/companion";
import { ApiError } from "../api/client";
import { openCheckpointsOf, projectsApi, type Plan } from "../api/projects";
import { metaFrom } from "../lib/conversationMeta";

beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

const base = {
  activeThreadId: "", onSelectThread: () => {}, onAddThread: () => {}, activeSection: "arslan" as const,
  onChangeSection: () => {}, onDistillThread: vi.fn(), onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(),
  onDeleteThread: vi.fn(), backendStatus: "online" as const,
};
const thread = (id: string, projectId?: string) => ({ id, title: `chat ${id}`, ...(projectId ? { projectId } : {}) });

describe("the sidebar's projects", () => {
  it("keeps a project's conversations under it and out of 最近", () => {
    render(<Sidebar {...base} threads={[thread("a", "p1"), thread("b"), thread("c", "p1")]}
      projects={[{ id: "p1", name: "Tidepool" }]} activeThreadId="a" />);
    const group = screen.getByTestId("sidebar-project-p1");
    // the active conversation's project starts open
    expect(within(group).getByText("chat a")).toBeInTheDocument();
    expect(within(group).getByText("chat c")).toBeInTheDocument();
    expect(screen.getAllByText("chat a")).toHaveLength(1);       // not repeated in 最近
    expect(screen.getByText("chat b")).toBeInTheDocument();
  });

  it("knows a conversation's project from the server too, not only from where it was started", () => {
    const meta = metaFrom([{ conversation_id: "x", title: "", message_count: 1, project_id: "p1" }]);
    render(<Sidebar {...base} threads={[thread("x")]} meta={meta} projects={[{ id: "p1", name: "Tidepool" }]} />);
    fireEvent.click(screen.getByTestId("sidebar-project-toggle-p1"));
    expect(within(screen.getByTestId("sidebar-project-p1")).getByText("chat x")).toBeInTheDocument();
  });

  it("opens and closes, starts a conversation in the project, and links to all of them", () => {
    const onStart = vi.fn();
    const onOpen = vi.fn();
    const many = Array.from({ length: PROJECT_CHATS + 2 }, (_, i) => thread(`t${i}`, "p1"));
    render(<Sidebar {...base} threads={many} projects={[{ id: "p1", name: "Tidepool" }]}
      onStartInProject={onStart} onOpenProject={onOpen} />);
    expect(screen.queryByText("chat t0")).toBeNull();                       // closed by default
    fireEvent.click(screen.getByTestId("sidebar-project-toggle-p1"));
    expect(screen.getByText("chat t0")).toBeInTheDocument();
    expect(screen.queryByText(`chat t${PROJECT_CHATS}`)).toBeNull();        // only the latest few
    fireEvent.click(screen.getByTestId("sidebar-project-all-p1"));
    expect(onOpen).toHaveBeenCalledWith("p1");
    fireEvent.click(screen.getByTestId("sidebar-project-new-p1"));
    expect(onStart).toHaveBeenCalledWith("p1");
    expect(JSON.parse(localStorage.getItem("arslan_sidebar_projects_open") ?? "[]")).toEqual(["p1"]);
  });

  it("groups at most a few projects; conversations of the rest stay in 最近", () => {
    const projects = Array.from({ length: SIDEBAR_PROJECTS + 1 }, (_, i) => ({ id: `p${i}`, name: `P${i}` }));
    const threads = projects.map((p, i) => thread(`t${i}`, p.id));
    render(<Sidebar {...base} threads={threads} projects={projects} onOpenProject={() => {}} />);
    expect(screen.getAllByTestId(/^sidebar-project-p\d+$/)).toHaveLength(SIDEBAR_PROJECTS);
    expect(screen.getByText(`chat t${SIDEBAR_PROJECTS}`)).toBeInTheDocument();   // its project is not grouped
  });

  it("a conversation's menu moves it into a project, or out of one", () => {
    const onMove = vi.fn();
    const { rerender } = render(<ThreadRowMenu threadId="t1" onDistill={vi.fn()} onArchive={vi.fn()} onDelete={vi.fn()}
      projects={[{ id: "p1", name: "Tidepool" }, { id: "p2", name: "Lisbon" }]} projectId={null} onMove={onMove} />);
    fireEvent.click(screen.getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByTestId("thread-move"));
    expect(screen.queryByTestId("thread-move-out")).toBeNull();
    fireEvent.click(screen.getByTestId("thread-move-to-p2"));
    expect(onMove).toHaveBeenLastCalledWith("t1", "p2");
    rerender(<ThreadRowMenu threadId="t1" onDistill={vi.fn()} onArchive={vi.fn()} onDelete={vi.fn()}
      projects={[{ id: "p1", name: "Tidepool" }, { id: "p2", name: "Lisbon" }]} projectId="p2" onMove={onMove} />);
    fireEvent.click(screen.getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByTestId("thread-move"));
    expect(screen.queryByTestId("thread-move-to-p2")).toBeNull();          // not to where it already is
    fireEvent.click(screen.getByTestId("thread-move-out"));
    expect(onMove).toHaveBeenLastCalledWith("t1", null);
  });
});

const PROJECT = { id: "p1", name: "Tidepool", kind: "general", summary: "", workspace_ref: null, collection_ids: [], app_binding: null,
  status: "active", version: 3, updated_at: "", template: "game", finish_line: "Ship", stage: "active" } as Project;
const plan = (secondDone: boolean): Plan => ({
  project_id: "p1", version: 5, stage: "active", paused: false, column: "doing", levels: [
    { id: "l2", name: "Slice", band: "doing", state: "current", started_at: new Date().toISOString(),
      checkpoints: [{ id: "c1", text: "Art direction", state: "done" }, { id: "c2", text: "First level", state: secondDone ? "done" : "todo" }] },
    { id: "l3", name: "Launch", band: "done", state: "todo", checkpoints: [] },
  ],
});
function mountPage(p: Plan, events: unknown[] = []) {
  vi.spyOn(companionApi, "projects").mockResolvedValue([PROJECT]);
  vi.spyOn(projectsApi, "plan").mockResolvedValue(p);
  vi.spyOn(projectsApi, "events").mockResolvedValue(events as never);
  vi.spyOn(projectsApi, "conversations").mockResolvedValue([]);
  render(<><ProjectPage projectId="p1" onBack={() => {}} onStart={vi.fn()} onPlan={() => {}} onChanged={() => {}} /><ConfirmHost /><ToastHost /></>);
}

describe("clearing a level", () => {
  it("everything done: one click, named after where it goes, with an undo", async () => {
    mountPage(plan(true));
    const advance = vi.spyOn(projectsApi, "advance").mockResolvedValue(plan(true));
    vi.mocked(projectsApi.events).mockResolvedValue([{ id: "adv1", kind: "advance", actor: "user", payload: {}, outcome: null, created_at: "" }] as never);
    const undo = vi.spyOn(projectsApi, "undo").mockResolvedValue(plan(true));
    const button = await screen.findByTestId("project-clear-level");
    expect(button).toHaveTextContent('projectsUI.clearNext:{"next":"Launch"}');
    expect(screen.queryByTestId("project-clear-early")).toBeNull();
    fireEvent.click(button);
    await waitFor(() => expect(advance).toHaveBeenCalledWith("p1", undefined));
    fireEvent.click(await screen.findByTestId("kit-toast-action"));
    await waitFor(() => expect(undo).toHaveBeenCalledWith("p1", "adv1"));
  });

  it("something open: the sheet lists it and sends the choice and the reason", async () => {
    mountPage(plan(false));
    expect(screen.queryByTestId("project-clear-level")).toBeNull();
    const advance = vi.spyOn(projectsApi, "advance").mockResolvedValue(plan(false));
    fireEvent.click(await screen.findByTestId("project-clear-early"));
    const sheet = await screen.findByTestId("leftover-sheet");
    expect(within(sheet).getByTestId("leftover-open")).toHaveTextContent("First level");
    fireEvent.click(within(sheet).getByTestId("leftover-drop").querySelector("input")!);
    fireEvent.change(within(sheet).getByTestId("leftover-note"), { target: { value: "not needed" } });
    fireEvent.click(within(sheet).getByTestId("leftover-confirm"));
    await waitFor(() => expect(advance).toHaveBeenCalledWith("p1", { leftover: "drop", note: "not needed" }));
    await waitFor(() => expect(screen.queryByTestId("leftover-sheet")).toBeNull());
  });

  it("not yet: nothing is sent", async () => {
    mountPage(plan(false));
    const advance = vi.spyOn(projectsApi, "advance");
    fireEvent.click(await screen.findByTestId("project-clear-early"));
    fireEvent.click(within(await screen.findByTestId("leftover-sheet")).getByTestId("leftover-cancel"));
    expect(advance).not.toHaveBeenCalled();
  });

  it("your own clears are listed with an undo, not only Arslan's", async () => {
    mountPage(plan(false), [{ id: "adv9", kind: "advance", actor: "user", payload: { level: "Idea", next: "Slice" }, outcome: null, created_at: "" }]);
    const recent = await screen.findByTestId("project-recent");
    await waitFor(() => expect(recent).toHaveTextContent("projectsUI.recentAdvanceYou"));
    expect(screen.getByTestId("project-undo-adv9")).toBeInTheDocument();
  });

  it("accepting Arslan's proposal with checkpoints open asks the same question", async () => {
    const card = { id: "p1", name: "Tidepool", template: "game", kind: "general", finish_line: "Ship", stage: "active", paused: false,
      column: "doing", levels: [], current: null, left: 2, done_at: null, has_plan: true,
      proposal: { id: "e1", level: "Slice", next: "Launch", evidence: { kind: "said", quote: "done" }, moves_column: false, last: false,
        open: [{ id: "c2", text: "First level" }] } };
    vi.spyOn(projectsApi, "board").mockResolvedValue({ cards: [card], counts: { paused: 0, archived: 0 },
      shadow: { proposed: 0, accepted: 0, streak: 0, ask_at: 10, asked: false, auto_advance: false } } as never);
    const refused = new ApiError("open", 409, { code: "open_checkpoints", open: [{ id: "c2", text: "First level" }] });
    const decide = vi.spyOn(projectsApi, "decide").mockRejectedValueOnce(refused).mockResolvedValueOnce(plan(false));
    render(<ProjectsSection onStart={vi.fn()} />);
    expect(await screen.findByTestId("project-proposal-open-p1")).toHaveTextContent('projectsUI.proposalOpen:{"count":1}');
    fireEvent.click(screen.getByTestId("project-accept-p1"));
    const sheet = await screen.findByTestId("leftover-sheet");
    fireEvent.click(within(sheet).getByTestId("leftover-confirm"));
    await waitFor(() => expect(decide).toHaveBeenLastCalledWith("p1", "e1", true, "move"));
  });

  it("reads the open checkpoints only from an open_checkpoints refusal", () => {
    expect(openCheckpointsOf(new ApiError("x", 409, { code: "open_checkpoints", open: [{ id: "a", text: "A" }] }))).toEqual([{ id: "a", text: "A" }]);
    expect(openCheckpointsOf(new ApiError("x", 409, { code: "proposal_decided" }))).toBeNull();
    expect(openCheckpointsOf(new Error("x"))).toBeNull();
  });
});
