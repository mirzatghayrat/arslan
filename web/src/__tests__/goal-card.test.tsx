// L7-6: the goal card, its edit step, "Keep going until met" and the composer chip (docs/plans/0164/L7-goal-mode.md,
// UI, "The frame"). The frames are the card's own pinned vectors, read from the card.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GoalState } from "../api/client.types";
import JobCard from "../components/JobCard";
import { GoalChip, editLines, objectiveOf } from "../components/GoalCard";
import { jobMessages } from "../locales/jobs";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, string>) =>
    opts ? `${key}:${Object.values(opts).join("|")}` : key }),
}));

const card = readFileSync(resolve(__dirname, "../../../docs/plans/0164/L7-goal-mode.md"), "utf8");
function vector(name: string): GoalState {
  const line = card.split("\n").find((l) => l.trim().startsWith(`- ${name}: \`{`))!;
  return JSON.parse(line.split("`")[1]);
}
const NOT_STARTED = vector("not started");
const ACTIVE = vector("active, round 3");
const BLOCKED: GoalState = { ...ACTIVE, status: "blocked", round: 6, blocker: { code: "no_progress", files: [] },
  step: "Type the amount of INV-1052 in a note." };

const frame = (goal_state?: GoalState, over: Record<string, unknown> = {}) => ({
  type: "job_update" as const, job_id: "job-1", conversation_id: "c",
  goal: "Reconcile the October invoices check: python3 check_totals.py", phase: "running" as const, step: "read_file",
  outcome: null, detail: "", criteria: [], ...(goal_state ? { goal_state } : {}), ...over,
});

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function show(goal_state?: GoalState, over: Record<string, unknown> = {}, props: Record<string, unknown> = {}) {
  useArslanStore.getState().handleFrame(frame(goal_state, over));
  const onSend = vi.fn();
  render(<JobCard jobId="job-1" onSend={onSend} {...props} />);
  return onSend;
}

describe("store", () => {
  it("keeps no goal state for a job that is not a goal", () => {
    useArslanStore.getState().handleFrame(frame());
    expect("goalState" in useArslanStore.getState().jobs["job-1"]).toBe(false);
  });

  it("keeps a goal's state as the frame sent it", () => {
    useArslanStore.getState().handleFrame(frame(ACTIVE));
    expect(useArslanStore.getState().jobs["job-1"].goalState).toEqual(ACTIVE);
  });
});

describe("edit step", () => {
  it("keeps Start goal disabled until a flagged check is marked as yours, then sends the edit and Start", () => {
    const onSend = show(NOT_STARTED, { phase: "queued" });
    const start = screen.getByText("jobs.goal.start").closest("button")!;
    expect(start).toBeDisabled();
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(start).not.toBeDisabled();
    fireEvent.click(start);
    expect(onSend).toHaveBeenCalledWith(
      "/goal edit start job-1\nobjective: Reconcile the October invoices\nc1: Summary sheet saved\nc2 (mine): Looks tidy");
  });

  it("sends a plain /goal start, naming the goal (L7-5h), when nothing was changed and nothing is flagged", () => {
    const onSend = show({ ...NOT_STARTED, checks: NOT_STARTED.checks.slice(0, 1) }, { phase: "queued" });
    fireEvent.click(screen.getByText("jobs.goal.start"));
    expect(onSend).toHaveBeenCalledWith("/goal start job-1");
  });

  it("removes a check, adds one that stays flagged, and Cancel clears a goal that isn't started", () => {
    const onSend = show(NOT_STARTED, { phase: "queued" });
    fireEvent.click(screen.getByLabelText("jobs.goal.removeN:2"));
    expect(screen.getByText("jobs.goal.start").closest("button")).not.toBeDisabled();
    fireEvent.click(screen.getByText("jobs.goal.add"));
    fireEvent.change(screen.getByLabelText("jobs.goal.check:2"), { target: { value: "totals add up" } });
    expect(screen.getByText("jobs.goal.start").closest("button")).toBeDisabled();
    fireEvent.click(screen.getByText("jobs.goal.cancel"));
    expect(onSend).toHaveBeenCalledWith("/goal clear");
  });

  it("writes a command check back as its check: line with its declared outputs", () => {
    expect(editLines("Fix it", [{ id: "check-1", text: "python3 run.py", kind: "check", mine: false, flagged: false,
      outputs: ["tests/revealed/test_step_*.py"] }], false)).toBe(
      "/goal edit\nobjective: Fix it\ncheck: python3 run.py outputs: tests/revealed/test_step_*.py");
  });
});

describe("objective", () => {
  it("drops the check: lines, and only those", () => {
    expect(objectiveOf("Tidy the notes check: python3 run.py")).toBe("Tidy the notes");
    expect(objectiveOf("Run the recheck: it must pass")).toBe("Run the recheck: it must pass");
  });
});

describe("goal card", () => {
  it("shows the round, n of m, spend against the cap, the tier and each receipt", () => {
    show(ACTIVE);
    expect(screen.getByTestId("goal-meta").textContent).toBe(
      "jobs.goal.round:3jobs.goal.metOf:1|2jobs.goal.spend:0.41|2.00jobs.goal.tier.standard");
    expect(screen.getByTestId("goal-check-c1").textContent).toContain("october-summary.xlsx");
    expect(screen.getByTestId("goal-check-check-1").textContent).toContain("jobs.goal.exited:1");
    expect(screen.getByText("Reconcile the October invoices")).toBeInTheDocument();   // no check: line in the title
  });

  it("sends Pause and Note as chat lines, and Edit opens the same form", () => {
    const onSend = show(ACTIVE);
    fireEvent.click(screen.getByText("jobs.goal.pause"));
    expect(onSend).toHaveBeenLastCalledWith("/goal pause");
    fireEvent.click(screen.getByText("jobs.goal.note"));
    fireEvent.change(screen.getByLabelText("jobs.goal.noteLabel"), { target: { value: "credits are in credits/" } });
    fireEvent.click(screen.getByText("jobs.goal.sendNote"));
    expect(onSend).toHaveBeenLastCalledWith("/goal note credits are in credits/");
    fireEvent.click(screen.getByText("jobs.goal.edit"));
    fireEvent.click(screen.getByText("jobs.goal.start"));
    expect(onSend.mock.lastCall?.[0]).toMatch(/^\/goal edit start job-1\nobjective: Reconcile the October invoices\nc1: /);
  });

  it("says what blocks it and the one step, and Resume sends /goal resume naming the goal (L7-5h)", () => {
    const onSend = show(BLOCKED, { phase: "finished", outcome: "blocked" });
    expect(screen.getByTestId("goal-blocker").textContent).toBe("jobs.goal.blockedBy:jobs.goal.blocker.no_progress");
    expect(screen.getByTestId("goal-step").textContent).toBe(`jobs.goal.step:${BLOCKED.step}`);
    expect(screen.queryByText("jobs.goal.pause")).toBeNull();
    fireEvent.click(screen.getByText("jobs.goal.resume"));
    expect(onSend).toHaveBeenCalledWith("/goal resume job-1");
  });

  it("shows an interrupted goal's round with one Resume", () => {
    show({ ...ACTIVE, status: "interrupted", round: 4 }, { phase: "finished", outcome: "interrupted" });
    expect(screen.getByTestId("goal-meta").textContent).toContain("jobs.goal.roundAt.interrupted:4");
    expect(screen.getAllByText("jobs.goal.resume")).toHaveLength(1);
    expect(screen.getByText("jobs.goal.hint.interrupted:4")).toBeInTheDocument();
  });

  it("warns about check: files missing at Start", () => {
    show({ ...ACTIVE, missing_files: ["scripts/check_totals.py"] });
    expect(screen.getByText("jobs.goal.missing:scripts/check_totals.py")).toBeInTheDocument();
  });
});

describe("keep going until met", () => {
  it("is offered on a job that fell short, with goal mode on, and sets a goal from it", () => {
    const onSend = show(undefined, { phase: "finished", outcome: "partial" }, { goalMode: true });
    fireEvent.click(screen.getByTestId("keep-going"));
    expect(onSend).toHaveBeenCalledWith("/goal from job-1");
  });

  it("is not offered with goal mode off, or on a job that is done", () => {
    show(undefined, { phase: "finished", outcome: "partial" });
    expect(screen.queryByTestId("keep-going")).toBeNull();
    cleanup();
    show(undefined, { phase: "finished", outcome: "done" }, { goalMode: true });
    expect(screen.queryByTestId("keep-going")).toBeNull();
  });
});

describe("chip", () => {
  it("shows an open goal's objective and n of m, and nothing for a job that is not a goal or a done goal", () => {
    useArslanStore.getState().handleFrame(frame());
    const { rerender } = render(<GoalChip />);
    expect(screen.queryByTestId("goal-chip")).toBeNull();
    useArslanStore.getState().handleFrame(frame(ACTIVE));
    rerender(<GoalChip />);
    expect(screen.getByTestId("goal-chip").textContent).toBe("Reconcile the October invoicesjobs.goal.chipCount:1|2");
    useArslanStore.getState().handleFrame(frame({ ...ACTIVE, status: "complete" }, { phase: "finished" }));
    rerender(<GoalChip />);
    expect(screen.queryByTestId("goal-chip")).toBeNull();
  });
});

describe("locales", () => {
  it("has every goal string in all six languages", () => {
    const keys = (o: object, prefix = ""): string[] => Object.entries(o).flatMap(([k, v]) =>
      typeof v === "object" ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`]);
    const en = keys(jobMessages.en.goal).sort();
    for (const locale of ["zh", "ja", "es", "de", "fr"] as const) expect(keys(jobMessages[locale].goal).sort()).toEqual(en);
  });
});

describe("a goal a newer one took over from (L7-5h)", () => {
  it("keeps its card as it was: Resume and Stop name it, and it can't be edited here", () => {
    const onSend = show({ ...BLOCKED, left: true }, { phase: "finished", outcome: "blocked" });
    expect(screen.getByTestId("goal-blocker")).toBeTruthy();
    expect(screen.queryByText("jobs.goal.edit")).toBeNull();
    fireEvent.click(screen.getByText("jobs.goal.resume"));
    expect(onSend).toHaveBeenLastCalledWith("/goal resume job-1");
    fireEvent.click(screen.getByText("jobs.goal.stop"));
    expect(onSend).toHaveBeenLastCalledWith("/goal clear job-1");
  });

  it("its running card (the job's own frame) never offers Edit (#989 review r2 MF2)", () => {
    show({ ...ACTIVE, left: true }, { phase: "running" });
    expect(screen.getByText("jobs.goal.pause")).toBeTruthy();
    expect(screen.queryByText("jobs.goal.edit")).toBeNull();
  });

  it("one that never started shows its card, not the edit form, and Start names it", () => {
    const onSend = show({ ...NOT_STARTED, left: true }, { phase: "queued" });
    expect(screen.queryByTestId("goal-form")).toBeNull();
    fireEvent.click(screen.getByText("jobs.goal.start"));
    expect(onSend).toHaveBeenLastCalledWith("/goal start job-1");
  });
});
