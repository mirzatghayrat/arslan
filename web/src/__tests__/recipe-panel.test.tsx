import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../i18n";
import RecipePanel from "../components/RecipePanel";
import { recipeApi } from "../api/recipes";

vi.mock("../api/recipes", () => ({ recipeApi: {
  versions: vi.fn(), executions: vi.fn(), save: vi.fn(), start: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
} }));
vi.mock("../components/RunReplay", () => ({ default: ({ runId }: { runId: number }) => <div>Trace {runId}</div> }));
const version = { id: 7, key: "research", version: 1, name: "Research", spec: {
  name: "Research", max_parallel: 2, steps: [{ key: "a", name: "Collect", spawn_id: 1,
    task: "Collect evidence", depends_on: [], requires_approval: false }],
} };

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(recipeApi.versions).mockResolvedValue([version]);
  vi.mocked(recipeApi.executions).mockResolvedValue([]);
});

describe("recipe editor and execution controls", () => {
  it("builds dependency and approval fields into an immutable version", async () => {
    vi.mocked(recipeApi.save).mockResolvedValue(version);
    render(<RecipePanel spawns={[{ id: "1", name: "Researcher" }]} />);
    await screen.findByText("No recipe executions yet.");
    fireEvent.change(screen.getByLabelText("Recipe name"), { target: { value: "Research" } });
    fireEvent.click(screen.getByText("Add step"));
    fireEvent.change(screen.getByLabelText("Step 1 task"), { target: { value: "Collect evidence" } });
    fireEvent.click(screen.getByText("Add step"));
    fireEvent.change(screen.getByLabelText("Step 2 task"), { target: { value: "Synthesize" } });
    fireEvent.click(screen.getByLabelText("Step 1"));
    fireEvent.click(screen.getAllByLabelText("Ask for my approval before this step")[1]);
    fireEvent.click(screen.getByText("Save new version"));
    await waitFor(() => expect(recipeApi.save).toHaveBeenCalled());
    const saved = vi.mocked(recipeApi.save).mock.calls[0][1];
    expect(saved.steps[1].depends_on).toEqual(["step1"]);
    expect(saved.steps[1].requires_approval).toBe(true);
    expect(recipeApi.start).not.toHaveBeenCalled();
  });

  it("reuses the request key after an uncertain start and runs only the saved version", async () => {
    vi.mocked(recipeApi.start).mockRejectedValueOnce(new Error("lost response")).mockResolvedValueOnce({
      id: 9, recipe_id: 7, input: "Evidence", status: "queued", checkpoint: {},
    });
    render(<RecipePanel spawns={[{ id: "1", name: "Researcher" }]} />);
    await screen.findByText("Research · v1");
    fireEvent.change(screen.getByLabelText("Choose a saved version"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Input for this run"), { target: { value: "Evidence" } });
    fireEvent.change(screen.getByLabelText("Step 1 task"), { target: { value: "Unsaved edit" } });
    fireEvent.click(screen.getByText("Run saved version"));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByText("Run saved version"));
    await waitFor(() => expect(recipeApi.start).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(recipeApi.start).mock.calls;
    expect(calls[0]).toEqual(calls[1]);
    expect(calls[0].slice(0, 2)).toEqual([7, "Evidence"]);
    expect(recipeApi.save).not.toHaveBeenCalled();
  });

  it("requires a second explicit confirmation before replaying unfinished effects", async () => {
    vi.mocked(recipeApi.executions).mockResolvedValue([{ id: 4, recipe_id: 7, input: "task", status: "interrupted",
      checkpoint: { steps: { a: { status: "interrupted", run_id: 17 } } }, run_id: 16 }]);
    render(<RecipePanel spawns={[]} />);
    fireEvent.click(await screen.findByText("Review and resume"));
    expect(recipeApi.resume).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent("possible external effects");
    expect(screen.getByRole("dialog")).toHaveTextContent("Saved task budgets and approval limits remain in force");
    fireEvent.click(screen.getByText("Confirm retry of unfinished steps"));
    await waitFor(() => expect(recipeApi.resume).toHaveBeenCalledWith(4, [], true));
    fireEvent.click(screen.getAllByText("Details and files")[0]);
    expect(screen.getByText("Trace 17")).toBeInTheDocument();
  });
});
