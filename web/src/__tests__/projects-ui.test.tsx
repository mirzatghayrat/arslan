/** 0.1.56 P2: the projects board, a new project, and a project's page. */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key),
    i18n: { resolvedLanguage: "en", language: "en" },
  }),
}));

import ProjectsBoard from "../components/projects/ProjectsBoard";
import NewProject from "../components/projects/NewProject";
import ProjectPage from "../components/projects/ProjectPage";
import { ConfirmHost } from "../components/kit";
import { companionApi, type Project } from "../api/companion";
import { projectsApi, type Board, type BoardCard, type Level, type Plan } from "../api/projects";
import { OPEN_CONVERSATION_EVENT } from "../lib/openConversation";

const card = (over: Partial<BoardCard>): BoardCard => ({
  id: "p1", name: "Tidepool", template: "game", kind: "general", finish_line: "On the App Store", stage: "active",
  paused: false, column: "doing", levels: [{ name: "Idea", band: "shaping", state: "cleared" }, { name: "Slice", band: "doing", state: "current" },
    { name: "Launch", band: "done", state: "todo" }],
  current: { position: 2, name: "Slice", started_at: new Date(Date.now() - 3 * 86_400_000).toISOString() },
  left: 2, proposal: null, done_at: null, has_plan: true, ...over,
});
const board = (cards: BoardCard[], over: Partial<Board> = {}): Board => ({
  cards, counts: { paused: 1, archived: 2 },
  shadow: { proposed: 7, accepted: 6, streak: 4, ask_at: 10, asked: false, auto_advance: false }, ...over,
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the board", () => {
  it("puts each card in the column the server derived, with its level and what is left", () => {
    render(<ProjectsBoard board={board([card({}), card({ id: "p2", name: "Lisbon", column: "idea", template: "trip", has_plan: true,
      current: null, levels: [{ name: "Dates", band: "shaping", state: "todo" }], left: 1 }), card({ id: "p3", name: "Old", column: "idea",
      template: null, kind: "research", has_plan: false, levels: [], current: null, left: 0 })])}
      onOpen={() => {}} onNew={() => {}} onPlan={() => {}} onDecide={() => {}} />);
    const doing = screen.getByTestId("projects-col-doing");
    expect(within(doing).getByTestId("project-card-p1")).toHaveTextContent('projectsUI.level:{"n":2}');
    expect(within(doing).getByTestId("project-card-p1")).toHaveTextContent('projectsUI.left:{"count":2}');
    expect(within(doing).getByTestId("project-card-p1")).toHaveTextContent('projectsUI.dayIn:{"days":4}');
    expect(within(screen.getByTestId("projects-col-idea")).getByTestId("project-card-p2")).toBeInTheDocument();
    // A project from before 0.1.56 shows its old kind's type, and offers to plan it.
    const old = screen.getByTestId("project-card-p3");
    expect(old).toHaveTextContent("projectsUI.type_research");
    expect(within(old).getByTestId("project-plan-p3")).toBeInTheDocument();
    expect(screen.getByTestId("projects-counts")).toHaveTextContent('projectsUI.paused:{"count":1}');
    expect(screen.getByTestId("projects-shadow")).toHaveTextContent('"streak":4');
  });

  it("a proposal waits on its card with its evidence; the user moves it on or not", () => {
    const onDecide = vi.fn();
    const c = card({ proposal: { id: "e1", level: "Slice", next: "Production", evidence: { kind: "said", quote: "slice looks right" },
      moves_column: false, last: false } });
    render(<ProjectsBoard board={board([c])} onOpen={() => {}} onNew={() => {}} onPlan={() => {}} onDecide={onDecide} />);
    expect(screen.getByTestId("project-proposal-p1")).toHaveTextContent("slice looks right");
    fireEvent.click(screen.getByTestId("project-accept-p1"));
    fireEvent.click(screen.getByTestId("project-decline-p1"));
    expect(onDecide.mock.calls).toEqual([[c, true], [c, false]]);
  });

  it("the last level's proposal never offers to finish the project for the user", () => {
    const c = card({ proposal: { id: "e2", level: "Launch", next: null, evidence: { kind: "said", quote: "it is out" }, moves_column: false, last: true } });
    render(<ProjectsBoard board={board([c])} onOpen={() => {}} onNew={() => {}} onPlan={() => {}} onDecide={() => {}} />);
    expect(screen.getByTestId("project-proposal-p1")).toHaveTextContent("projectsUI.proposalLast");
    expect(screen.queryByTestId("project-decline-p1")).toBeNull();
    expect(screen.getByTestId("project-accept-p1")).toHaveTextContent("projectsUI.gotIt");
  });

  it("dropped projects fold under Done; the list view shows every project", () => {
    render(<ProjectsBoard board={board([card({}), card({ id: "p9", name: "Gone", column: "dropped" })])}
      onOpen={() => {}} onNew={() => {}} onPlan={() => {}} onDecide={() => {}} />);
    expect(screen.queryByTestId("project-card-p9")).toBeNull();
    fireEvent.click(screen.getByTestId("projects-dropped-toggle"));
    expect(screen.getByTestId("project-card-p9")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("projects-view-list"));
    expect(within(screen.getByTestId("projects-list")).getAllByRole("row")).toHaveLength(3);
  });
});

const drafted = (finish = ""): Level[] => [
  { name: "Idea", band: "shaping", checkpoints: [] },
  { name: "Launch", band: "done", clear_condition: finish, checkpoints: [] },
];

describe("a new project", () => {
  beforeEach(() => {
    vi.spyOn(projectsApi, "draft").mockImplementation(async (template, finish) => ({
      levels: template === "trip" ? [{ name: "Dates", band: "shaping", checkpoints: [] }, { name: "Leave", band: "done", clear_condition: finish, checkpoints: [] }]
        : drafted(finish), source: "template" }));
  });

  it("drafts the levels for the type; the finish line becomes the last level's condition", async () => {
    render(<NewProject onDone={() => {}} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("plan-level-1")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("new-project-finish"), { target: { value: "On the App Store" } });
    expect(within(screen.getByTestId("plan-level-1")).getByLabelText("projectsUI.clearCondition")).toHaveValue("On the App Store");
    fireEvent.click(screen.getByTestId("new-project-type-trip"));
    await waitFor(() => expect(within(screen.getByTestId("plan-level-0")).getByLabelText("projectsUI.levelName")).toHaveValue("Dates"));
    expect(projectsApi.draft).toHaveBeenLastCalledWith("trip", "On the App Store", "en");
  });

  it("an edited condition is not overwritten by the finish line", async () => {
    render(<NewProject onDone={() => {}} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("plan-level-1")).toBeInTheDocument());
    const condition = within(screen.getByTestId("plan-level-1")).getByLabelText("projectsUI.clearCondition");
    fireEvent.change(condition, { target: { value: "My own words" } });
    fireEvent.change(screen.getByTestId("new-project-finish"), { target: { value: "Something else" } });
    expect(condition).toHaveValue("My own words");
  });

  it("creates the project with its type, finish line and folder, then saves the plan", async () => {
    const created = { id: "new-1" } as Project;
    const create = vi.spyOn(companionApi, "createProject").mockResolvedValue(created);
    const save = vi.spyOn(projectsApi, "savePlan").mockResolvedValue({} as Plan);
    const onDone = vi.fn();
    render(<NewProject onDone={onDone} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("plan-level-1")).toBeInTheDocument());
    expect(screen.getByTestId("new-project-create")).toBeDisabled();          // no name yet
    fireEvent.click(screen.getByTestId("new-project-type-game"));
    fireEvent.change(screen.getByTestId("new-project-name"), { target: { value: "Tidepool" } });
    fireEvent.change(screen.getByTestId("new-project-finish"), { target: { value: "On the App Store" } });
    fireEvent.change(screen.getByTestId("new-project-folder"), { target: { value: "~/Arslan/Tidepool" } });
    await waitFor(() => expect(screen.getByTestId("new-project-create")).toBeEnabled());
    fireEvent.click(screen.getByTestId("new-project-create"));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("new-1"));
    expect(create.mock.calls[0][0]).toMatchObject({ name: "Tidepool", template: "game", finish_line: "On the App Store",
      workspace_ref: "~/Arslan/Tidepool" });
    expect(save.mock.calls[0][0]).toBe("new-1");
    expect(save.mock.calls[0][1]).toBe(0);
    expect(save.mock.calls[0][2].map((l: Level) => l.name)).toEqual(["Idea", "Launch"]);
  });

  it("a level with no name cannot be saved", async () => {
    render(<NewProject onDone={() => {}} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("plan-level-0")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("new-project-name"), { target: { value: "X" } });
    fireEvent.change(within(screen.getByTestId("plan-level-0")).getByLabelText("projectsUI.levelName"), { target: { value: " " } });
    expect(screen.getByTestId("new-project-create")).toBeDisabled();
  });
});

const PROJECT = { id: "p1", name: "Tidepool", kind: "general", summary: "", workspace_ref: null, collection_ids: [], app_binding: null,
  status: "active", version: 3, updated_at: "", template: "game", finish_line: "On the App Store", stage: "active" } as Project;
const PLAN: Plan = {
  project_id: "p1", version: 5, stage: "active", paused: false, column: "doing", levels: [
    { id: "l1", name: "Idea", band: "shaping", state: "cleared", checkpoints: [] },
    { id: "l2", name: "Slice", band: "doing", state: "current", started_at: new Date().toISOString(), clear_condition: "It plays end to end",
      checkpoints: [{ id: "c1", text: "Art direction", state: "done", done_by: "arslan", evidence: { kind: "said", quote: "go with B" } },
        { id: "c2", text: "First level", state: "todo" }] },
    { id: "l3", name: "Launch", band: "done", state: "todo", checkpoints: [] },
  ],
};

function mountPage(onStart = vi.fn().mockResolvedValue(undefined)) {
  vi.spyOn(companionApi, "projects").mockResolvedValue([PROJECT]);
  vi.spyOn(projectsApi, "plan").mockResolvedValue(PLAN);
  vi.spyOn(projectsApi, "events").mockResolvedValue([
    { id: "ev1", kind: "tick", actor: "arslan", payload: { text: "Art direction", evidence: { kind: "said", quote: "go with B" } }, outcome: null, created_at: "" },
    { id: "ev0", kind: "tick", actor: "arslan", payload: { text: "Old" }, outcome: "undone", created_at: "" },
    { id: "ev2", kind: "plan_change", actor: "user", payload: {}, outcome: null, created_at: "" },
  ]);
  vi.spyOn(projectsApi, "conversations").mockResolvedValue([{ conversation_id: "c-9", messages: 4, last_at: null, opening: "Draw the art" }]);
  render(<><ProjectPage projectId="p1" onBack={() => {}} onStart={onStart} onPlan={() => {}} onChanged={() => {}} /><ConfirmHost /></>);
  return onStart;
}

describe("a project's page", () => {
  it("shows the current level, its checkpoints with evidence, and what to do next", async () => {
    mountPage();
    expect(await screen.findByTestId("level-map")).toBeInTheDocument();
    expect(screen.getByTestId("level-node-1")).toHaveAttribute("data-state", "current");
    const cps = screen.getByTestId("project-checkpoints");
    expect(within(cps).getByTestId("checkpoint-c1")).toBeChecked();
    expect(cps).toHaveTextContent("go with B");
    expect(cps).toHaveTextContent("It plays end to end");
    expect(screen.getByTestId("project-next")).toHaveTextContent("First level");
    expect(screen.getByTestId("project-left")).toHaveTextContent('"count":2');
  });

  it("hand to Arslan opens a project conversation with the request typed, not sent", async () => {
    const onStart = mountPage();
    fireEvent.click(await screen.findByTestId("project-hand-off"));
    expect(onStart).toHaveBeenCalledTimes(1);
    const [project, prefill] = onStart.mock.calls[0];
    expect(project.id).toBe("p1");
    expect(prefill).toContain("projectsUI.handOffText");
    expect(prefill).toContain("First level");
  });

  it("ticking, clearing by hand and undoing go through the API", async () => {
    mountPage();
    const tick = vi.spyOn(projectsApi, "tick").mockResolvedValue(PLAN);
    const advance = vi.spyOn(projectsApi, "advance").mockResolvedValue(PLAN);
    const undo = vi.spyOn(projectsApi, "undo").mockResolvedValue(PLAN);
    fireEvent.click(await screen.findByTestId("checkpoint-c2"));
    await waitFor(() => expect(tick).toHaveBeenCalledWith("p1", "c2", true));
    fireEvent.click(screen.getByTestId("project-clear-level"));
    await waitFor(() => expect(advance).toHaveBeenCalledWith("p1"));
    // Only Arslan's own, not-undone steps are listed for undo.
    const recent = screen.getByTestId("project-recent");
    expect(recent).toHaveTextContent('projectsUI.recentTick:{"text":"Art direction"}');
    expect(recent).not.toHaveTextContent('"text":"Old"');
    fireEvent.click(screen.getByTestId("project-undo-ev1"));
    await waitFor(() => expect(undo).toHaveBeenCalledWith("p1", "ev1"));
  });

  it("dropping asks first; done and pause are one click", async () => {
    mountPage();
    const stage = vi.spyOn(projectsApi, "stage").mockResolvedValue(PLAN);
    fireEvent.click(await screen.findByTestId("project-drop"));
    expect(stage).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId("confirm-action"));
    await waitFor(() => expect(stage).toHaveBeenCalledWith("p1", { stage: "dropped" }));
    fireEvent.click(screen.getByTestId("project-pause"));
    await waitFor(() => expect(stage).toHaveBeenCalledWith("p1", { paused: true }));
  });

  it("its conversations open in the chat", async () => {
    mountPage();
    fireEvent.click(await screen.findByTestId("project-tab-conversations"));
    const seen: unknown[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(OPEN_CONVERSATION_EVENT, on);
    fireEvent.click(screen.getByText("Draw the art"));
    window.removeEventListener(OPEN_CONVERSATION_EVENT, on);
    expect(seen).toEqual(["c-9"]);
  });

  it("changing the plan sends the plan's own version", async () => {
    mountPage();
    const save = vi.spyOn(projectsApi, "savePlan").mockResolvedValue(PLAN);
    fireEvent.click(await screen.findByTestId("project-edit-plan"));
    fireEvent.click(await screen.findByTestId("project-save-plan"));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toBe("p1");
    expect(save.mock.calls[0][1]).toBe(5);
  });
});

describe("the project client", () => {
  it("an edit sends the type and finish line, so the API does not clear them", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await companionApi.editProject(PROJECT, PROJECT);
    const body = JSON.parse(String((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body));
    expect(body.project).toMatchObject({ template: "game", finish_line: "On the App Store" });
    vi.unstubAllGlobals();
  });
});

describe("refining the draft with the model (P3)", () => {
  it("is one call on the button, with what the editor shows; a failure keeps the draft", async () => {
    const draft = vi.spyOn(projectsApi, "draft")
      .mockResolvedValueOnce({ levels: drafted(), source: "template" })
      .mockResolvedValueOnce({ levels: [{ name: "Pitch", band: "shaping", checkpoints: [] }, { name: "Ship", band: "done", checkpoints: [] }], source: "model" })
      .mockResolvedValueOnce({ levels: [{ name: "Pitch", band: "shaping", checkpoints: [] }, { name: "Ship", band: "done", checkpoints: [] }], source: "template", refine_failed: true });
    render(<NewProject onDone={() => {}} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("plan-level-1")).toBeInTheDocument());
    expect(draft).toHaveBeenCalledTimes(1);                                    // the template draft: no model
    expect(screen.getByText("projectsUI.refineHint")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("new-project-refine"));
    await waitFor(() => expect(within(screen.getByTestId("plan-level-0")).getByLabelText("projectsUI.levelName")).toHaveValue("Pitch"));
    expect(draft.mock.calls[1][3]).toEqual({ refine: true, levels: drafted() });
    expect(screen.getByText("projectsUI.refined")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("new-project-refine"));
    await waitFor(() => expect(screen.getByText("projectsUI.refineFailed")).toBeInTheDocument());
  });
});

import PlanProposalCard from "../components/projects/PlanProposalCard";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { toUiMessages } from "../api/adapters";

const PROPOSAL = { id: "pp1", reason: "no online mode", cleared: 3, diff: [
  { op: "add" as const, level: "Six more levels", band: "doing" as const },
  { op: "remove" as const, level: "Stress test" },
  { op: "change" as const, level: "Beta", added: ["Solo playtest"], removed: [], band: null },
] };

describe("a changed plan, proposed (P3)", () => {
  it("shows what changes and keeps cleared levels; taking it goes through the projects API", async () => {
    const decide = vi.spyOn(projectsApi, "decidePlan").mockResolvedValue(PLAN);
    const onDone = vi.fn();
    render(<PlanProposalCard projectId="p1" proposal={PROPOSAL} onDone={onDone} />);
    const diff = screen.getByTestId("plan-diff");
    expect(diff).toHaveTextContent('projectsUI.diffAdd:{"level":"Six more levels"}');
    expect(diff).toHaveTextContent('projectsUI.diffRemove:{"level":"Stress test"}');
    expect(diff).toHaveTextContent('"added":"Solo playtest"');
    expect(diff).toHaveTextContent('projectsUI.diffKept:{"count":3}');
    expect(screen.getByTestId("plan-proposal")).toHaveTextContent("no online mode");
    fireEvent.click(screen.getByTestId("plan-proposal-take"));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("p1", "pp1", true));
    expect(await screen.findByTestId("plan-proposal-decided")).toHaveTextContent("projectsUI.planTaken");
    expect(onDone).toHaveBeenCalled();
  });

  it("keeping the plan declines it", async () => {
    const decide = vi.spyOn(projectsApi, "decidePlan").mockResolvedValue(PLAN);
    render(<PlanProposalCard projectId="p1" proposal={PROPOSAL} />);
    fireEvent.click(screen.getByTestId("plan-proposal-keep"));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("p1", "pp1", false));
    expect(await screen.findByTestId("plan-proposal-decided")).toHaveTextContent("projectsUI.planKept");
  });

  it("the plan_proposed frame becomes a card in the conversation", () => {
    useArslanStore.setState(initialArslanState());
    useArslanStore.getState().handleFrame({ type: "plan_proposed", project_id: "p1", proposal_id: "pp1", diff: PROPOSAL.diff,
      reason: "no online mode", cleared: 3 });
    const items = useArslanStore.getState().items;
    expect(items[items.length - 1]).toMatchObject({ kind: "plan", planProposal: { projectId: "p1", id: "pp1", cleared: 3 } });
    const messages = toUiMessages(items);
    expect(messages[messages.length - 1].planProposal).toMatchObject({ projectId: "p1", id: "pp1" });
  });

  it("an open proposal shows on the project page too", async () => {
    vi.spyOn(companionApi, "projects").mockResolvedValue([PROJECT]);
    vi.spyOn(projectsApi, "plan").mockResolvedValue({ ...PLAN, plan_proposal: PROPOSAL });
    vi.spyOn(projectsApi, "events").mockResolvedValue([]);
    vi.spyOn(projectsApi, "conversations").mockResolvedValue([]);
    render(<ProjectPage projectId="p1" onBack={() => {}} onStart={async () => {}} onPlan={() => {}} onChanged={() => {}} />);
    expect(await screen.findByTestId("plan-proposal")).toBeInTheDocument();
  });
});
