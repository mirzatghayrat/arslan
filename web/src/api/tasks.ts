import { request } from "./client";

export interface TaskRef { id: string; kind: string; revision: number; sha256?: string | null; locator?: string | null }
export type TaskPhase = "queued" | "running" | "waiting_user" | "verifying" | "succeeded" | "failed" | "cancelled";
export interface TaskFrame {
  type: "task_state"; task_id: string; conversation_id: string; attempt_id: string;
  sequence: number; phase: TaskPhase; version: number; pause_reason: string | null;
}
export interface TaskSummary {
  version: number; conversation_id: string; pause_reason: string | null; cancel_requested: boolean;
  spec: { id: string; revision: number; instruction: string; locale: string;
    acceptance: { id: string; description: string; evaluator: "human" | "model" | "deterministic" }[] };
  state: { task_id: string; spec_revision: number; run_id: string; sequence: number; phase: TaskPhase;
    checkpoint_ref: string | null; results: { check_id: string; status: "passed" | "failed" | "unverified" | "not_run" | "not_applicable"; evaluator: string; evidence: TaskRef[] }[] };
  budget: { id: string; used: Record<string, number>; limits: Record<string, number>; stop_reason: string | null };
}
export interface TaskAction {
  id: string; version: number; tool_key: string; effect: string;
  status: "prepared" | "in_flight" | "succeeded" | "failed" | "uncertain" | "denied" | "not_applied";
  evidence: TaskRef[]; error_code: string | null;
}
export interface TaskDetail extends TaskSummary {
  validation?: { spec_revision: number; attempt_id: string; output_sha256: string;
    checks: { check_id: string; status: string; evaluator: string; code: string }[];
    artifacts: { id: string; filename: string; title?: string; run_id?: number; url?: string;
      status: string; code: string; sha256?: string; bytes?: number }[] } | null;
  workers?: TaskWorker[];
  checkpoint: { progress: { completed_steps: string[]; artifacts: TaskRef[]; pending_actions: string[] } } | null;
  attempts: { id: string; number: number; status: string; run_ids: number[] }[];
  actions: TaskAction[];
}
export interface TaskWorker {
  id: string; method: string; method_revision: number; objective: string; run_id: number | null;
  status: "queued" | "running" | "completed" | "partial" | "failed" | "cancelled" | "interrupted";
  result: { status: string; result: string; artifacts: TaskRef[]; evidence: { kind: string; url: string }[]; remaining_work: string[] } | null;
}
const json = (body: unknown) => ({ method: "POST", body: JSON.stringify(body) });
export const tasksApi = {
  list: (conversationId: string, offset = 0) => request<TaskSummary[]>(`/tasks?conversation_id=${encodeURIComponent(conversationId)}&limit=20&offset=${offset}`),
  detail: (id: string) => request<TaskDetail>(`/tasks/${encodeURIComponent(id)}`),
  cancel: (task: TaskSummary) => request<TaskSummary>(`/tasks/${encodeURIComponent(task.spec.id)}/cancel`, json({})),
  accept: (task: TaskSummary) => request<TaskSummary>(`/tasks/${encodeURIComponent(task.spec.id)}/accept`, json({ expected_version: task.version })),
  reconcile: (taskId: string, action: TaskAction, applied: boolean, note: string) => request<TaskSummary>(
    `/tasks/${encodeURIComponent(taskId)}/actions/${encodeURIComponent(action.id)}/reconcile`,
    json({ expected_version: action.version, applied, note })),
};
