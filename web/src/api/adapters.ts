import type { AppSettings, Spawn } from "../types";
import type { AppSettings as BackendAppSettings, SpawnSummary } from "./client.types";

// ── Settings adapters ─────────────────────────────────────────────────────────

// Backend masked value sentinel (the server returns this literal when a key is set but masked).
const MASKED_SENTINEL_RE = /^[•*]+$/;

/**
 * Maps a backend AppSettings (snake_case) → UI AppSettings (camelCase).
 *
 * Field mapping:
 *   llm_provider   → llmProvider
 *   llm_model      → llmModel
 *   llm_api_key    → apiKeyLLM  (may be "" or masked "••…")
 *   search_provider → searchProvider
 *   search_api_key  → apiKeySearch (may be "" or masked)
 *   language       → language
 *
 * UI-only fields with no backend counterpart are kept at their current UI value
 * and therefore should NOT be overwritten on fetch; callers must merge:
 *   theme, telemetry, spawnMode
 */
export function toUiSettings(backend: BackendAppSettings): Omit<AppSettings, "theme" | "telemetry" | "spawnMode"> {
  return {
    llmProvider: backend.llm_provider ?? "",
    llmModel: backend.llm_model ?? "",
    apiKeyLLM: backend.llm_api_key ?? "",
    searchProvider: backend.search_provider ?? "",
    apiKeySearch: backend.search_api_key ?? "",
    language: backend.language ?? "en",
  };
}

/**
 * Maps UI AppSettings (camelCase) → backend body (snake_case) for PUT /api/v1/settings.
 *
 * Masked-key handling: if the user did NOT type a new key (value is empty or still
 * matches the masked sentinel pattern), we omit that field from the PUT body so the
 * backend keeps the existing stored value.
 */
export function toBackendSettings(ui: AppSettings): Partial<BackendAppSettings> {
  const body: Partial<BackendAppSettings> = {
    llm_provider: ui.llmProvider,
    llm_model: ui.llmModel,
    search_provider: ui.searchProvider,
    language: ui.language,
  };

  // Only send keys if the user entered something new (non-empty, non-masked).
  if (ui.apiKeyLLM && !MASKED_SENTINEL_RE.test(ui.apiKeyLLM)) {
    body.llm_api_key = ui.apiKeyLLM;
  }
  if (ui.apiKeySearch && !MASKED_SENTINEL_RE.test(ui.apiKeySearch)) {
    body.search_api_key = ui.apiKeySearch;
  }

  return body;
}

// ── Spawn adapters ────────────────────────────────────────────────────────────

/**
 * Maps a backend SpawnSummary DTO to the UI Spawn shape used by AI Studio components.
 *
 * Key mappings:
 * - id: number  →  id: string (String(id))
 * - total_tasks: number  →  totalTasks: number
 * - capabilities: string[]  →  tools/skills (passthrough as tools; skills empty unless provided)
 * - status: backend has no status field, default to "idle"
 * - avatarEmoji: default "🤖"
 */
export function toUiSpawn(s: SpawnSummary & {
  status?: string;
  tools?: string[];
  skills?: string[];
  total_tasks?: number;
  description?: string;
}): Spawn {
  return {
    id: String(s.id),
    name: s.name,
    domain: s.domain ?? "",
    description: s.description ?? "",
    status: (s.status as Spawn["status"]) ?? "idle",
    avatarEmoji: "🤖",
    tools: s.tools ?? s.capabilities ?? [],
    skills: s.skills ?? [],
    totalTasks: s.total_tasks ?? 0,
  };
}
