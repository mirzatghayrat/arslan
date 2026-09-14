import { ApiError } from "../../api/client";

export function companionError(error: unknown): string {
  if (error instanceof ApiError) {
    const taskKey = taskErrorKey(error.message);
    if (taskKey) return taskKey;
    if (["credentials_not_memory", "credentials_not_project_metadata", "credentials_not_method_data"].includes(error.message)) return "companion.credentialError";
    if (error.message === "conversation_running") return "companion.runningSettings";
    if (error.message.includes("version_conflict")) return "companion.conflict";
    if (error.message === "style_reference_conflict") return "design.referenceConflict";
    if (error.message === "style_reference_project_required") return "design.scopeHint";
    if (error.message.includes("confirmation") || error.message.includes("restricted")) return "companion.reviewRequired";
  }
  return "companion.failure";
}

export function taskErrorKey(code: string): string | null {
  if (code === "task_validation_failed") return "validation.failedReason";
  if (code === "task_artifact_changed") return "validation.changedReason";
  if (code === "task_checks_not_run") return "validation.notRunReason";
  if (code === "process_interrupted") return "tasks.interrupted";
  if (code === "backup_restore_review_required") return "tasks.restored";
  if (code === "task_reconciliation_required") return "tasks.uncertain";
  if (code === "task_budget_exhausted") return "tasks.budgetExhausted";
  if (code === "task_no_progress") return "tasks.noProgress";
  if (code === "task_input_required") return "tasks.inputRequired";
  if (code === "task_memory_changed") return "tasks.memoryChanged";
  if (code === "task_memory_check_failed") return "tasks.memoryCheckFailed";
  if (code === "task_local_model_required") return "tasks.localRequired";
  if (code === "task_project_changed") return "tasks.projectChanged";
  if (code === "conversation_local_history") return "tasks.localHistory";
  if (code === "execution_failed" || code === "task_execution_failed") return "tasks.executionFailed";
  if (code === "task_version_conflict" || code === "task_attempt_stale") return "companion.conflict";
  if (code === "credentials_not_task_data" || code === "credentials_not_review_data") return "companion.credentialError";
  return null;
}
