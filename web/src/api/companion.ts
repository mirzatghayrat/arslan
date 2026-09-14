import { request } from "./client";

export type MemoryScope = { kind: "global" | "project" | "domain" | "expert"; id: string | null };
export type MemoryStatus = "proposed" | "active" | "paused" | "superseded" | "expired" | "deleted" | "quarantined";
export interface StyleReference {
  source_kind: "file" | "url" | "library" | "artifact";
  source_ref: string;
  polarity: "positive" | "negative";
  rationale: string;
  interpretation: "tentative" | "confirmed";
}
export interface MemoryWrite {
  content: string;
  kind: "preference" | "project_fact" | "style_rule" | "experience";
  scope: MemoryScope;
  sensitivity: "normal" | "sensitive" | "unknown";
  use_policy: "local_only" | "cloud_allowed";
  sensitive_acknowledged?: boolean;
  topic?: string | null;
  style_reference?: StyleReference | null;
  valid_from?: string | null;
  review_at?: string | null;
  expires_at?: string | null;
}
export interface MemoryEntry extends Omit<MemoryWrite, "sensitivity" | "use_policy" | "content"> {
  content: string | null;
  id: string;
  version: number;
  revision_id: string;
  status: MemoryStatus;
  sensitivity: "normal" | "sensitive" | "unknown" | "secret";
  use_policy: "local_only" | "cloud_allowed" | "never";
  confirmed_at: string | null;
  valid_from: string | null;
  review_at: string | null;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
  sources: { id: string; revision_id: string; kind: string; author: string; reference: Record<string, unknown> }[];
}
export interface ProjectInput {
  name: string;
  kind: "general" | "software" | "research" | "design";
  summary: string;
  workspace_ref: string | null;
  collection_ids: number[];
  app_binding: { app_id: string | null; bundle_id: string | null; connection_id?: string | null;
    version_id?: string | null; platform?: "IOS" | "MAC_OS" | "TV_OS" | "VISION_OS" | null } | null;
}
export interface Project extends ProjectInput {
  id: string;
  version: number;
  status: "active" | "archived";
  updated_at: string;
}
export interface ConversationContext {
  conversation_id: string;
  version: number;
  project_id: string | null;
  no_memory: boolean;
  no_learning: boolean;
  temporary: boolean;
  cloud_memory_allowed: boolean;
  allow_sensitive: boolean;
}
export interface MemoryProposal {
  id: number;
  target_id: string;
  target_version: number;
  candidate: MemoryWrite | null;
  reason: string;
  entry: MemoryEntry;
}
export interface MemoryRevision {
  id: string; version: number; content: string | null; change_reason: string; created_at: string;
  style_reference?: StyleReference | null;
}
export type ContextFilterReason = "scope" | "permission" | "deleted" | "inactive" | "sensitive" | "irrelevant" | "budget";
export interface ContextReceiptRecord {
  id: string;
  created_at: string;
  receipt: {
    id: string; task_id: string; run_id: string;
    memory_mode: "normal" | "disabled" | "temporary";
    used: { id: string; kind: string; revision: number }[];
    filter_reasons: ContextFilterReason[];
    estimated_tokens: number;
    cloud_use: "not_sent" | "approved";
    local_only_used: boolean;
  };
}
export interface ContextMemoryReview {
  id: string; recorded_version: number; current_version: number | null;
  entry_status: MemoryStatus | null;
  status: "available" | "deleted" | "unavailable";
  content: string | null;
}
const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });
const projectBody = ({ name, kind, summary, workspace_ref, collection_ids, app_binding }: ProjectInput): ProjectInput =>
  ({ name, kind, summary, workspace_ref, collection_ids, app_binding });
export const companionApi = {
  projects: (includeArchived = false) => request<Project[]>(`/projects${includeArchived ? "?include_archived=true" : ""}`),
  createProject: (body: ProjectInput) => request<Project>("/projects", json("POST", projectBody(body))),
  editProject: (project: Project, body: ProjectInput, status = project.status) => request<Project>(
    `/projects/${encodeURIComponent(project.id)}`, json("PUT", { expected_version: project.version, project: projectBody(body), status })),
  memories: (offset = 0) => request<MemoryEntry[]>(`/memory/entries?limit=100&offset=${offset}`),
  createMemory: (body: MemoryWrite) => request<MemoryEntry>("/memory/entries", json("POST", body)),
  editMemory: (entry: MemoryEntry, body: MemoryWrite, confirmScopeChange: boolean) => request<MemoryEntry>(
    `/memory/entries/${encodeURIComponent(entry.id)}`, json("PUT", {
      expected_version: entry.version, memory: body, confirm_scope_change: confirmScopeChange,
    })),
  setMemoryStatus: (entry: MemoryEntry, status: "active" | "paused") => request<MemoryEntry>(
    `/memory/entries/${encodeURIComponent(entry.id)}/status`, json("POST", { expected_version: entry.version, status })),
  deleteMemory: (entry: MemoryEntry) => request(`/memory/entries/${encodeURIComponent(entry.id)}?expected_version=${entry.version}`,
    { method: "DELETE" }),
  history: (entryId: string) => request<MemoryRevision[]>(`/memory/entries/${encodeURIComponent(entryId)}/history`),
  proposals: (offset = 0) => request<MemoryProposal[]>(`/memory/proposals?limit=100&offset=${offset}`),
  resolveProposal: (id: number, accept: boolean, sensitive: boolean, cloud: boolean) => request(
    `/memory/proposals/${id}/resolve`, json("POST", { accept, sensitive_acknowledged: sensitive,
      use_policy: cloud ? "cloud_allowed" : "local_only" })),
  context: (conversationId: string) => request<ConversationContext>(`/conversations/${encodeURIComponent(conversationId)}/context`),
  contextReceipts: (conversationId: string, taskId: string, beforeId?: string) => request<ContextReceiptRecord[]>(
    `/conversations/${encodeURIComponent(conversationId)}/context/receipts?task_id=${encodeURIComponent(taskId)}&limit=20`
    + (beforeId ? `&before_id=${encodeURIComponent(beforeId)}` : "")),
  contextMemory: (conversationId: string, receiptId: string, entryId: string) => request<ContextMemoryReview>(
    `/conversations/${encodeURIComponent(conversationId)}/context/receipts/${encodeURIComponent(receiptId)}/memories/${encodeURIComponent(entryId)}`),
  saveContext: (context: ConversationContext, changes: Partial<ConversationContext>) => {
    const { conversation_id, version, ...settings } = { ...context, ...changes };
    return request<ConversationContext>(`/conversations/${encodeURIComponent(conversation_id)}/context`,
      json("PUT", { ...settings, expected_version: version }));
  },
};
