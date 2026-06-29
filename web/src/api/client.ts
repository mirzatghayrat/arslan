import { useAuthStore } from "../stores/authStore";
import type {
  AppSettings,
  CatalogEntry,
  ConfirmResult,
  EvolutionStats,
  EvolveProposal,
  IngestResult,
  KnowledgeSource,
  ProviderConfig,
  ProviderOption,
  RegistryCatalog,
  RunDetailDto,
  RunListItem,
  SpawnDetail,
  SpawnSummary,
  SuggestDraft,
  SuggestPrimaryResult,
  TemplateInfo,
  UserFact,
} from "./client.types";

// Configurable for desktop (Tauri) builds; empty = same-origin relative URLs.
export const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "").replace(/\/+$/, "");
const BASE = `${API_BASE}/api/v1`;

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const resp = await fetch(`${BASE}${path}`, {
    method: init.method ?? "GET",
    ...init,
    headers,
  });

  if (resp.status === 204) return undefined as T;

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      // keep default
    }
    throw new ApiError(detail, resp.status);
  }
  return (await resp.json()) as T;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),
  listSpawns: () => request<SpawnSummary[]>("/spawns"),
  draftSpawn: (description: string) =>
    request<SuggestDraft>("/spawns/draft", { method: "POST", body: JSON.stringify({ description }) }),
  createSpawn: (body: { name: string; domain: string; capabilities: string[]; persona_role?: string | null; persona_tone?: string | null }) =>
    request<SpawnDetail>("/spawns", { method: "POST", body: JSON.stringify(body) }),
  getSpawn: (id: number) => request<SpawnDetail>(`/spawns/${id}`),
  deleteSpawn: (id: number) => request<void>(`/spawns/${id}`, { method: "DELETE" }),
  updateConfig: (id: number, body: Partial<SpawnDetail>) =>
    request<SpawnDetail>(`/spawns/${id}/config`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  getEvolution: (id: number) => request<EvolutionStats>(`/spawns/${id}/evolution`),
  sendFeedback: (
    id: number,
    body: { message_id?: number; user_action: string; edits?: Record<string, unknown> },
  ) =>
    request<void>(`/spawns/${id}/feedback`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listTemplates: () => request<TemplateInfo[]>("/templates"),
  getSettings: () => request<AppSettings>("/settings"),
  listProviders: () => request<ProviderOption[]>("/settings/providers"),
  listSearchProviders: () => request<string[]>("/settings/search-providers"),
  updateSettings: (body: Partial<AppSettings>) =>
    request<AppSettings>("/settings", { method: "PUT", body: JSON.stringify(body) }),
  getRegistry: () => request<RegistryCatalog>("/registry"),
  updateEquipment: (id: number, body: { toolsets: string[]; skills: string[] }) =>
    request<SpawnDetail>(`/spawns/${id}/equipment`, { method: "PUT", body: JSON.stringify(body) }),
  listFacts: () => request<UserFact[]>("/facts"),
  addFact: (body: { content: string; sensitive?: boolean }) =>
    request<UserFact>("/facts", { method: "POST", body: JSON.stringify(body) }),
  updateFact: (id: number, body: { content?: string; sensitive?: boolean }) =>
    request<UserFact>(`/facts/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteFact: (id: number) => request<void>(`/facts/${id}`, { method: "DELETE" }),
  /** Generate a concise thread title from the first user message + optional first reply. */
  generateTitle: (firstMessage: string, firstReply?: string): Promise<{ title: string }> =>
    request<{ title: string }>("/orchestrator/title", {
      method: "POST",
      body: JSON.stringify({ first_message: firstMessage, first_reply: firstReply }),
    }),
  getRun: (id: number) => request<RunDetailDto>(`/runs/${id}`),
  getRuns: (spawnId?: number, limit = 50) => {
    const qs = new URLSearchParams();
    if (spawnId != null) qs.set("spawn_id", String(spawnId));
    qs.set("limit", String(limit));
    return request<RunListItem[]>(`/runs?${qs.toString()}`);
  },
  getKnowledge: (spawnId: number) =>
    request<KnowledgeSource[]>(`/spawns/${spawnId}/knowledge`),
  ingestKnowledgeText: (spawnId: number, source: string, text: string, compress = false) =>
    request<IngestResult>(`/spawns/${spawnId}/knowledge`, {
      method: "POST",
      body: JSON.stringify({ source, text, compress }),
    }),
  ingestKnowledgeFile: async (spawnId: number, file: File, compress = false): Promise<IngestResult> => {
    const token = useAuthStore.getState().token;
    const form = new FormData();
    form.append("file", file);
    form.append("compress", String(compress));
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const resp = await fetch(`${BASE}/spawns/${spawnId}/knowledge`, {
      method: "POST",
      body: form,
      headers,
    });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try { detail = (await resp.json()).detail ?? detail; } catch { /* keep */ }
      throw new ApiError(detail, resp.status);
    }
    return (await resp.json()) as IngestResult;
  },
  ingestKnowledgeUrl: (spawnId: number, url: string, compress = false) =>
    request<IngestResult>(`/spawns/${spawnId}/knowledge`, {
      method: "POST",
      body: JSON.stringify({ url, compress }),
    }),
  deleteKnowledge: (spawnId: number, source: string) =>
    request<{ deleted: number }>(
      `/spawns/${spawnId}/knowledge?source=${encodeURIComponent(source)}`,
      { method: "DELETE" },
    ),
  getPreferences: (spawnId: number) =>
    request<{ preferences: string[] }>(`/spawns/${spawnId}/preferences`),
  deletePreference: (spawnId: number, fact: string) =>
    request<{ preferences: string[] }>(`/spawns/${spawnId}/preferences`, {
      method: "DELETE",
      body: JSON.stringify({ fact }),
    }),
  evolveSpawn: (spawnId: number) =>
    request<EvolveProposal>(`/spawns/${spawnId}/evolve`, { method: "POST" }),
  confirmProposal: (proposalId: number) =>
    request<ConfirmResult>(`/evolution/proposals/${proposalId}/confirm`, { method: "POST" }),
  listMcpServers: () => request<Array<{ id: number; label: string; status?: string }>>("/mcp/servers"),
  completeChat: (id: number) => request<{ ok: boolean; archived: number }>(`/spawns/${id}/complete-chat`, { method: "POST" }),
  extractAttachmentUrl: (url: string, compress = false) =>
    request<{ text: string; chars: number; truncated: boolean }>(`/extract`, {
      method: "POST",
      body: JSON.stringify({ url, compress }),
    }),
  extractAttachmentFile: async (file: File, compress = false): Promise<{ text: string; chars: number; truncated: boolean }> => {
    const token = useAuthStore.getState().token;
    const form = new FormData();
    form.append("file", file);
    form.append("compress", String(compress));
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const resp = await fetch(`${BASE}/extract`, { method: "POST", body: form, headers });
    if (!resp.ok) { let detail = `HTTP ${resp.status}`; try { detail = (await resp.json()).detail ?? detail; } catch { /* keep */ } throw new ApiError(detail, resp.status); }
    return (await resp.json()) as { text: string; chars: number; truncated: boolean };
  },
};

// ── Provider Config CRUD ───────────────────────────────────────────────────────

export const listProviderConfigs = () =>
  request<ProviderConfig[]>("/settings/provider-configs");

export const addProviderConfig = (body: Omit<ProviderConfig, "id" | "is_primary">) =>
  request<ProviderConfig>("/settings/provider-configs", { method: "POST", body: JSON.stringify(body) });

export const updateProviderConfig = (id: number, body: Partial<ProviderConfig>) =>
  request<ProviderConfig>(`/settings/provider-configs/${id}`, { method: "PUT", body: JSON.stringify(body) });

export const setPrimaryProviderConfig = (id: number) =>
  request<{ ok: boolean }>(`/settings/provider-configs/${id}/primary`, { method: "PATCH" });

export const deleteProviderConfig = (id: number) =>
  request<{ ok: boolean }>(`/settings/provider-configs/${id}`, { method: "DELETE" });

export const suggestPrimary = () =>
  request<SuggestPrimaryResult | null>("/settings/suggest-primary");

export const getCatalog = () =>
  request<CatalogEntry[]>("/settings/catalog");

// ── LLM connection test endpoints (UX1) ───────────────────────────────────────

export interface TestLlmBody {
  provider: string;
  model: string;
  base_url?: string;
  api_key?: string;
}

export interface TestLlmResult {
  ok: boolean;
  error?: string;
  latency_ms?: number;
}

/** Test an ad-hoc set of credentials (for new/draft configs). */
export const testLlm = (body: TestLlmBody) =>
  request<TestLlmResult>("/settings/test-llm", {
    method: "POST",
    body: JSON.stringify(body),
  });

/** Test a saved provider config by id. */
export const testProviderConfig = (id: number) =>
  request<TestLlmResult>(`/settings/provider-configs/${id}/test`, {
    method: "POST",
  });
