import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import OngoingTasks from "../components/companion/OngoingTasks";
import { tasksApi, type TaskSummary } from "../api/tasks";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const row = { conversation_id: "another-conversation", spec: { id: "task-one", instruction: "Prepare the report" },
  state: { phase: "waiting_user" } } as TaskSummary;

it("shows a task from another conversation and opens it without resuming execution", async () => {
  vi.spyOn(tasksApi, "active").mockResolvedValue([row]);
  const open = vi.fn();
  render(<OngoingTasks onOpen={open} />);
  fireEvent.click(await screen.findByRole("button", { name: /Prepare the report/ }));
  expect(open).toHaveBeenCalledWith(row);
  expect(tasksApi.active).toHaveBeenCalledWith();
});

it("does not claim there are no tasks when the endpoint is unavailable", async () => {
  vi.spyOn(tasksApi, "active").mockRejectedValue(new Error("offline"));
  render(<OngoingTasks onOpen={() => {}} />);
  expect(await screen.findByText("workspace.taskListUnavailable")).toBeInTheDocument();
  expect(screen.queryByText("workspace.noOngoing")).toBeNull();
});

it("does not relabel terminal tasks from older backends as ongoing", async () => {
  vi.spyOn(tasksApi, "active").mockResolvedValue([{ ...row, state: { ...row.state, phase: "succeeded" } }]);
  render(<OngoingTasks onOpen={() => {}} />);
  expect(await screen.findByText("workspace.noOngoing")).toBeInTheDocument();
  expect(screen.queryByText("Prepare the report")).toBeNull();
});
