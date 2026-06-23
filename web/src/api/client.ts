import { useAuthStore } from "../stores/authStore";
import type {
  AppSettings,
  CatalogEntry,
  EvolutionStats,
  ProviderConfig,
  ProviderOption,
  RegistryCatalog,
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

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
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
