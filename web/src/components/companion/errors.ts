import { ApiError } from "../../api/client";

export function companionError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.message === "credentials_not_memory" || error.message === "credentials_not_project_metadata") return "companion.credentialError";
    if (error.message === "conversation_running") return "companion.runningSettings";
    if (error.message.includes("version_conflict")) return "companion.conflict";
    if (error.message.includes("confirmation") || error.message.includes("restricted")) return "companion.reviewRequired";
  }
  return "companion.failure";
}
