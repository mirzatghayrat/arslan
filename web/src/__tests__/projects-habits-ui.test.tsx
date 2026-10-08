/** 0.1.56 P5: shadow mode on the board, the habits sheet, stalled cards, the settings switch. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key),
    i18n: { resolvedLanguage: "en", language: "en" },
  }),
}));

import ShadowStrip from "../components/projects/ShadowStrip";
import ProjectCard from "../components/projects/ProjectCard";
import HabitsSheet from "../components/projects/HabitsSheet";
import ProjectsSection from "../components/companion/ProjectsSection";
import { companionApi, type Project } from "../api/companion";
import { projectsApi, type Board, type BoardCard, type Habits, type Shadow } from "../api/projects";
import { toBackendSettingsPatch, toUiSettings } from "../api/adapters";

const shadow = (over: Partial<Shadow> = {}): Shadow => ({
  proposed: 10, accepted: 10, streak: 10, ask_at: 10, asked: false, auto_advance: false,
  ask_due: false, offer_off: false, miss_is_latest: false, last_miss: null, ...over,
});
const card = (over: Partial<BoardCard> = {}): BoardCard => ({
  id: "p1", name: "Tidepool", template: "game", kind: "general", finish_line: null, stage: "active", paused: false,
  column: "shaping", levels: [{ name: "Idea", band: "shaping", state: "current" }, { name: "Launch", band: "done", state: "todo" }],
  current: { position: 1, name: "Idea", started_at: null }, left: 2, proposal: null, done_at: null, has_plan: true,
  stall: null, next: { id: "c1", text: "One-line pitch" }, ...over,
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); try { localStorage.clear(); } catch { /* none */ } });

describe("shadow mode on the board", () => {
  it("asks once at ten in a row: yes and not now both answer the ask", () => {
    const onAuto = vi.fn();
    render(<ShadowStrip shadow={shadow({ ask_due: true })} onAuto={onAuto} onNote={() => {}} onHabits={() => {}} />);
    expect(screen.getByTestId("projects-auto-ask")).toHaveTextContent('projectsUI.autoAsk:{"count":10}');
    fireEvent.click(screen.getByTestId("projects-auto-yes"));
    fireEvent.click(screen.getByTestId("projects-auto-no"));
    expect(onAuto.mock.calls).toEqual([[true, "ask"], [false, "ask"]]);
  });

  it("no ask unless it is due", () => {
    render(<ShadowStrip shadow={shadow()} onAuto={() => {}} onNote={() => {}} onHabits={() => {}} />);
    expect(screen.queryByTestId("projects-auto-ask")).toBeNull();
    expect(screen.queryByTestId("projects-auto-offer")).toBeNull();
  });

  it("after two undos it offers to stop; keeping it on is an answer too", () => {
    const onAuto = vi.fn();
    render(<ShadowStrip shadow={shadow({ auto_advance: true, offer_off: true })} onAuto={onAuto} onNote={() => {}} onHabits={() => {}} />);
    fireEvent.click(screen.getByTestId("projects-auto-off"));
    fireEvent.click(screen.getByTestId("projects-auto-keep"));
    expect(onAuto.mock.calls).toEqual([[false, "offer"], [true, "offer"]]);
  });

  it("right after a decline it offers one optional line; skipping is remembered", () => {
    const onNote = vi.fn();
    const miss = { id: "e9", project_id: "p1", level: "Slice", outcome: "declined" as const, note: null, at: "" };
    const { unmount } = render(<ShadowStrip shadow={shadow({ last_miss: miss, miss_is_latest: true })} onAuto={() => {}} onNote={onNote} onHabits={() => {}} />);
    expect(screen.getByTestId("projects-miss-note-save")).toBeDisabled();
    fireEvent.change(screen.getByTestId("projects-miss-note-input"), { target: { value: " one more pass " } });
    fireEvent.click(screen.getByTestId("projects-miss-note-save"));
    expect(onNote).toHaveBeenCalledWith("one more pass");
    fireEvent.click(screen.getByTestId("projects-miss-note-skip"));
    expect(screen.queryByTestId("projects-miss-note")).toBeNull();
    unmount();
    render(<ShadowStrip shadow={shadow({ last_miss: miss, miss_is_latest: true })} onAuto={() => {}} onNote={onNote} onHabits={() => {}} />);
    expect(screen.queryByTestId("projects-miss-note")).toBeNull();
  });

  it("no line for an old miss, an undo, or a miss that already has one", () => {
    const miss = { id: "e9", project_id: "p1", level: "Slice", outcome: "declined" as const, note: null, at: "" };
    for (const s of [shadow({ last_miss: miss, miss_is_latest: false }),
      shadow({ last_miss: { ...miss, outcome: "undone" }, miss_is_latest: true }),
      shadow({ last_miss: { ...miss, note: "said" }, miss_is_latest: true })]) {
      const { unmount } = render(<ShadowStrip shadow={s} onAuto={() => {}} onNote={() => {}} onHabits={() => {}} />);
      expect(screen.queryByTestId("projects-miss-note")).toBeNull();
      unmount();
    }
  });
});

describe("a stalled card", () => {
  it("says it quietly, with pick up / pause / change the plan", () => {
    const onResume = vi.fn(), onPause = vi.fn(), onOpen = vi.fn();
    render(<ProjectCard card={card({ stall: { days: 23, usual: 9, left: 2 } })} onOpen={onOpen} onDecide={() => {}} onPlan={() => {}}
      onResume={onResume} onPause={onPause} />);
    expect(screen.getByTestId("project-stall-p1")).toHaveTextContent('projectsUI.stallUsual:{"n":1,"days":23,"usual":9,"count":2}');
    fireEvent.click(screen.getByTestId("project-resume-p1"));
    fireEvent.click(screen.getByTestId("project-pause-p1"));
    fireEvent.click(screen.getByTestId("project-replan-p1"));
    expect([onResume.mock.calls.length, onPause.mock.calls.length, onOpen.mock.calls.length]).toEqual([1, 1, 1]);
  });

  it("a proposal waiting on the card comes first; no stall line under it", () => {
    render(<ProjectCard card={card({ stall: { days: 30, usual: null, left: 2 },
      proposal: { id: "e1", level: "Idea", next: "Launch", evidence: { kind: "said", quote: "ok" }, moves_column: false, last: false } })}
      onOpen={() => {}} onDecide={() => {}} onPlan={() => {}} />);
    expect(screen.queryByTestId("project-stall-p1")).toBeNull();
  });
});

const HABITS: Habits = {
  shadow: shadow({ last_miss: { id: "e1", project_id: "p1", level: "Slice", outcome: "declined", note: "one more pass", at: "" } }),
  rules: [
    { id: "r1", template: "game", text: "Include a level \"Art OK\".", enabled: true, sources: ["Sluice", "Tidepool"], created_at: "",
      value: { code: "add_level", name: "Art OK" } },
    { id: "r2", template: "game", text: "one more pass", enabled: false, sources: ["Tidepool"], created_at: "", value: { code: "note" } },
  ],
  pace: [{ template: "game", band: "shaping", levels: 4, median_days: 6.5, override_days: null }],
  cleared_levels: 4, pace_min_levels: 3,
};

describe("the habits sheet", () => {
  it("shows the meter, the last miss with what was learned, rules with sources, and pace", async () => {
    vi.spyOn(projectsApi, "habits").mockResolvedValue(HABITS);
    render(<HabitsSheet onBack={() => {}} />);
    expect(await screen.findByTestId("habits-last-miss")).toHaveTextContent('projectsUI.lastMissLearned:{"text":"one more pass"}');
    expect(screen.getByTestId("habit-rule-r1")).toHaveTextContent('projectsUI.ruleAddLevel:{"name":"Art OK"}');
    expect(screen.getByTestId("habit-rule-r1")).toHaveTextContent('"names":"Sluice, Tidepool"');
    expect(screen.getByTestId("habit-rule-r2")).toHaveTextContent('projectsUI.ruleSaid:{"text":"one more pass"}');
    expect(screen.getByTestId("habit-rule-switch-r2")).not.toBeChecked();
    expect(screen.getByTestId("pace-game-shaping")).toHaveTextContent('projectsUI.paceDays:{"count":6.5}');
  });

  it("a switch and a pace override go through the API", async () => {
    vi.spyOn(projectsApi, "habits").mockResolvedValue(HABITS);
    const setRule = vi.spyOn(projectsApi, "setRule").mockResolvedValue(HABITS);
    const setPace = vi.spyOn(projectsApi, "setPace").mockResolvedValue(HABITS);
    render(<HabitsSheet onBack={() => {}} />);
    fireEvent.click(await screen.findByTestId("habit-rule-switch-r2"));
    await waitFor(() => expect(setRule).toHaveBeenCalledWith("r2", true));
    fireEvent.change(screen.getByTestId("pace-input-game-shaping"), { target: { value: "4" } });
    fireEvent.click(screen.getByTestId("pace-save-game-shaping"));
    await waitFor(() => expect(setPace).toHaveBeenCalledWith("game", "shaping", 4));
    fireEvent.change(screen.getByTestId("pace-input-game-shaping"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("pace-save-game-shaping"));
    await waitFor(() => expect(setPace).toHaveBeenLastCalledWith("game", "shaping", null));
  });

  it("without enough history, pace says when it will show", async () => {
    vi.spyOn(projectsApi, "habits").mockResolvedValue({ ...HABITS, rules: [], pace: [], cleared_levels: 1 });
    render(<HabitsSheet onBack={() => {}} />);
    expect(await screen.findByTestId("habits-pace-none")).toHaveTextContent('"count":3,"done":1');
  });
});

describe("the projects section wires it together", () => {
  const PROJECT = { id: "p1", name: "Tidepool" } as unknown as Project;
  const BOARD = (over: Partial<Board> = {}): Board => ({ cards: [card({ stall: { days: 30, usual: null, left: 2 } })],
    counts: { paused: 0, archived: 0 }, shadow: shadow(), ...over });

  it("pick it up opens a project conversation at the next checkpoint, typed and linked", async () => {
    vi.spyOn(projectsApi, "board").mockResolvedValue(BOARD());
    vi.spyOn(companionApi, "projects").mockResolvedValue([PROJECT]);
    const onStart = vi.fn(async () => {});
    render(<ProjectsSection onStart={onStart} />);
    fireEvent.click(await screen.findByTestId("project-resume-p1"));
    await waitFor(() => expect(onStart).toHaveBeenCalledTimes(1));
    const [project, prefill, checkpointId] = (onStart.mock.calls[0] as unknown) as [Project, string, string];
    expect(project.id).toBe("p1");
    expect(prefill).toContain('"checkpoint":"One-line pitch"');
    expect(checkpointId).toBe("c1");
  });

  it("pause, the ask, and the decline's line reach the API", async () => {
    const miss = { id: "e9", project_id: "p7", level: "Slice", outcome: "declined" as const, note: null, at: "" };
    vi.spyOn(projectsApi, "board").mockResolvedValue(BOARD({ shadow: shadow({ ask_due: true, last_miss: miss, miss_is_latest: true }) }));
    const stage = vi.spyOn(projectsApi, "stage").mockResolvedValue({} as never);
    const auto = vi.spyOn(projectsApi, "autoAdvance").mockResolvedValue({} as never);
    const note = vi.spyOn(projectsApi, "note").mockResolvedValue({} as never);
    render(<ProjectsSection onStart={async () => {}} />);
    fireEvent.click(await screen.findByTestId("project-pause-p1"));
    await waitFor(() => expect(stage).toHaveBeenCalledWith("p1", { paused: true }));
    fireEvent.click(await screen.findByTestId("projects-auto-yes"));
    await waitFor(() => expect(auto).toHaveBeenCalledWith(true, "ask"));
    fireEvent.change(await screen.findByTestId("projects-miss-note-input"), { target: { value: "one more pass" } });
    fireEvent.click(screen.getByTestId("projects-miss-note-save"));
    await waitFor(() => expect(note).toHaveBeenCalledWith("p7", "e9", "one more pass"));
  });

  it("the footer opens the habits sheet", async () => {
    vi.spyOn(projectsApi, "board").mockResolvedValue(BOARD());
    vi.spyOn(projectsApi, "habits").mockResolvedValue(HABITS);
    render(<ProjectsSection onStart={async () => {}} />);
    fireEvent.click(await screen.findByTestId("projects-habits-open"));
    expect(await screen.findByTestId("habits-sheet")).toBeInTheDocument();
  });
});

describe("the settings switch", () => {
  it("round-trips as the plain string key", () => {
    expect(toBackendSettingsPatch({ projectsAutoAdvance: true })).toEqual({ projects_auto_advance: "true" });
    expect(toBackendSettingsPatch({ projectsAutoAdvance: false })).toEqual({ projects_auto_advance: "false" });
    expect(toUiSettings({ projects_auto_advance: "true" } as never).projectsAutoAdvance).toBe(true);
    expect(toUiSettings({} as never).projectsAutoAdvance).toBe(false);
  });
});
