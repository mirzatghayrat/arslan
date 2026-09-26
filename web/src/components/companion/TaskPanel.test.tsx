import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tasksApi, type TaskDetail } from "../../api/tasks";
import { taskMessages } from "../../locales/tasks";
import { initialArslanState, useArslanStore } from "../../stores/arslanStore";
import TaskPanel from "./TaskPanel";
import { validationMessages } from "../../locales/validation";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { resolvedLanguage: "en" } }),
}));

const task: TaskDetail = {
  version: 4, conversation_id: "conversation", pause_reason: "acceptance_review_required", cancel_requested: false,
  spec: { id: "task", revision: 1, instruction: "Prepare a checked document", locale: "en",
    acceptance: [{ id: "review", description: "Review", evaluator: "human" }] },
  state: { task_id: "task", spec_revision: 1, run_id: "attempt", sequence: 3, phase: "waiting_user", checkpoint_ref: "checkpoint", results: [] },
  budget: { id: "budget", used: { model_requests: 2, tool_calls: 1, tokens: 100, wall_seconds: 3 },
    limits: { model_requests: 32, tool_calls: 24, tokens: 128000, wall_seconds: 600 }, stop_reason: null },
  checkpoint: { progress: { completed_steps: ["done"], artifacts: [], pending_actions: [] } },
  attempts: [{ id: "attempt", number: 1, status: "waiting_user", run_ids: [1] }], actions: [],
};

beforeEach(() => {
  useArslanStore.setState(initialArslanState());
  vi.spyOn(tasksApi, "list").mockResolvedValue([task]);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("task controls", () => {
  it.each([
    ["task_memory_changed", "tasks.memoryChanged"],
    ["task_memory_check_failed", "tasks.memoryCheckFailed"],
  ])("shows %s as a reviewable pause requiring explicit resume", async (reason, key) => {
    const paused: TaskDetail = { ...task, pause_reason: reason };
    vi.mocked(tasksApi.list).mockResolvedValue([paused]);
    vi.spyOn(tasksApi, "detail").mockResolvedValue(paused);
    const resume = vi.fn();
    render(<TaskPanel conversationId="conversation" onResume={resume} />);
    fireEvent.click(await screen.findByRole("button", { name: /tasks.taskStatus/ }));
    expect(await screen.findByText(key)).toBeInTheDocument();
    expect(screen.queryByText("tasks.accept")).not.toBeInTheDocument();
    expect(resume).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("tasks.resume"));
    expect(resume).toHaveBeenCalledOnce();
    for (const messages of Object.values(taskMessages)) {
      expect(messages.memoryChanged.length).toBeGreaterThan(20);
      expect(messages.memoryCheckFailed.length).toBeGreaterThan(20);
    }
  });
  it("keeps failed and unperformed checks visible and blocks acceptance", async () => {
    const checked: TaskDetail = { ...task, pause_reason: "task_validation_failed", validation: {
      spec_revision: 1, attempt_id: "attempt", output_sha256: "a".repeat(64),
      checks: [{ check_id: "review", evaluator: "human", status: "not_run", code: "human_review_required" }],
      artifacts: [{ id: "artifact:broken", filename: "broken.pdf", status: "failed", code: "artifact_parse_failed" }],
    }, state: { ...task.state, results: [{ check_id: "review", evaluator: "human", status: "not_run", evidence: [] }] } };
    vi.mocked(tasksApi.list).mockResolvedValue([checked]);
    vi.spyOn(tasksApi, "detail").mockResolvedValue(checked);
    render(<TaskPanel conversationId="conversation" onResume={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /tasks.taskStatus/ }));
    expect(await screen.findByText("validation.failedReason")).toBeInTheDocument();
    expect(screen.getByText(/validation.human.*validation.not_run/)).toBeInTheDocument();
    expect(screen.getByText("validation.failed")).toBeInTheDocument();
    expect(screen.getByText("artifact:broken")).toBeInTheDocument();
    expect(screen.queryByText("tasks.accept")).not.toBeInTheDocument();
  });

  it("translates validation states in all six interface languages", () => {
    const keys = Object.keys(validationMessages.en).sort();
    expect(Object.keys(validationMessages).sort()).toEqual(["de", "en", "es", "fr", "ja", "zh"]);
    for (const messages of Object.values(validationMessages)) expect(Object.keys(messages).sort()).toEqual(keys);
  });
  it("requires an explicit review before accepting and works under Strict Mode", async () => {
    const accepted = { ...task, version: 5, pause_reason: null, state: { ...task.state, sequence: 4, phase: "succeeded" as const } };
    useArslanStore.getState().handleFrame({ type: "task_state", task_id: "task", conversation_id: "conversation",
      attempt_id: "attempt", sequence: 3, version: 4, phase: "waiting_user", pause_reason: "acceptance_review_required" });
    vi.spyOn(tasksApi, "detail").mockResolvedValueOnce(task).mockResolvedValue(accepted);
    const accept = vi.spyOn(tasksApi, "accept").mockResolvedValue(accepted);
    const resume = vi.fn();
    render(<StrictMode><TaskPanel conversationId="conversation" onResume={resume} /></StrictMode>);
    fireEvent.click(await screen.findByRole("button", { name: /tasks.taskStatus/ }));
    expect(await screen.findByText("tasks.accept")).toBeDisabled();
    expect(accept).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("tasks.acceptAck"));
    fireEvent.click(screen.getByText("tasks.accept"));
    await waitFor(() => expect(accept).toHaveBeenCalledWith(task));
    expect(await screen.findAllByText("tasks.succeeded")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: /tasks.taskStatus/ })).toHaveTextContent("tasks.succeeded");
    expect(resume).not.toHaveBeenCalled();
  });

  it("blocks uncertain writes and retains a failed verification draft", async () => {
    const uncertain: TaskDetail = { ...task, pause_reason: "task_reconciliation_required",
      actions: [{ id: "action", version: 2, tool_key: "publish", effect: "external_write", status: "uncertain", evidence: [], error_code: null }] };
    vi.mocked(tasksApi.list).mockResolvedValue([uncertain]);
    vi.spyOn(tasksApi, "detail").mockResolvedValue(uncertain);
    const reconcile = vi.spyOn(tasksApi, "reconcile").mockRejectedValue(new Error("offline"));
    const resume = vi.fn();
    render(<TaskPanel conversationId="conversation" onResume={resume} />);
    fireEvent.click(await screen.findByRole("button", { name: /tasks.taskStatus/ }));
    expect(await screen.findByText("tasks.resume")).toBeDisabled();
    fireEvent.click(screen.getByText("tasks.reviewAction"));
    expect(screen.getByLabelText("tasks.applied")).not.toBeChecked();
    expect(screen.getByLabelText("tasks.notApplied")).not.toBeChecked();
    fireEvent.change(screen.getByLabelText("tasks.reviewNote"), { target: { value: "I inspected the remote record and found no change." } });
    expect(screen.getByText("tasks.recordReview")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("tasks.notApplied"));
    fireEvent.click(screen.getByText("tasks.recordReview"));
    expect(await screen.findByRole("alert")).toHaveTextContent("companion.failure");
    expect(screen.getByLabelText("tasks.reviewNote")).toHaveValue("I inspected the remote record and found no change.");
    expect(screen.getByLabelText("tasks.notApplied")).toBeChecked();
    expect(reconcile).toHaveBeenCalledWith("task", uncertain.actions[0], false, "I inspected the remote record and found no change.");
    expect(resume).not.toHaveBeenCalled();
  });

  it("only resumes after a click and waits for a real execution confirmation", async () => {
    const interrupted: TaskDetail = { ...task, pause_reason: "process_interrupted" };
    vi.mocked(tasksApi.list).mockResolvedValue([interrupted]);
    vi.spyOn(tasksApi, "detail").mockResolvedValue(interrupted);
    const resume = vi.fn();
    render(<TaskPanel conversationId="conversation" onResume={resume} />);
    fireEvent.click(await screen.findByRole("button", { name: /tasks.taskStatus/ }));
    expect(await screen.findByText("tasks.resume")).toBeEnabled();
    expect(resume).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("tasks.resume"));
    expect(resume).toHaveBeenCalledWith(interrupted);
    expect(screen.getByRole("dialog")).toBeVisible();
    act(() => useArslanStore.getState().handleFrame({
      type: "task_state", task_id: "task", conversation_id: "conversation", attempt_id: "next",
      sequence: 5, version: 6, phase: "running", pause_reason: null,
    }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    act(() => useArslanStore.getState().handleFrame({
      type: "task_state", task_id: "task", conversation_id: "conversation", attempt_id: "attempt",
      sequence: 4, version: 5, phase: "waiting_user", pause_reason: "process_interrupted",
    }));
    expect(useArslanStore.getState().taskState?.phase).toBe("running");
  });

  it("rejects delayed frames even when another task intervened", () => {
    const frame = { type: "task_state" as const, task_id: "task", conversation_id: "conversation",
      attempt_id: "attempt", sequence: 9, version: 10, phase: "running" as const, pause_reason: null };
    const handle = useArslanStore.getState().handleFrame;
    handle(frame);
    handle({ ...frame, task_id: "other", sequence: 1 });
    handle({ ...frame, sequence: 8, phase: "waiting_user" });
    expect(useArslanStore.getState().taskState?.task_id).toBe("other");
    expect(useArslanStore.getState().taskSequences.task).toBe(9);
  });

  it("keeps all task labels aligned across six languages", () => {
    const keys = Object.keys(taskMessages.en).sort();
    for (const messages of Object.values(taskMessages)) {
      expect(Object.keys(messages).sort()).toEqual(keys);
      expect(Object.values(messages).every(value => value.trim().length > 0)).toBe(true);
    }
  });
});
