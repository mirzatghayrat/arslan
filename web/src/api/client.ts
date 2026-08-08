import { useAuthStore } from "../stores/authStore";
import type { CryptoHealth } from "../lib/cryptoHealth";
import type {
  AccessTokenInfo,
  AnomalyDto,
  AppSettings,
  CatalogEntry,
  CollectionOut,
  ConfirmResult,
  ConversationUsage,
  EmbeddingStatus,
  EvolutionStats,
  EvolveEstimate,
  EvolveEnqueued,
  ProposalListItem,
  ProposalDetail,
  SpawnDiagnosis,
  RefreshResult,
  RollbackResult,
  IngestResult,
  KnowledgeSource,
  ModelListResult,
  NoteDto,
  NoteSuggestDto,
  ProviderConfig,
  ProviderOption,
  RegistryCatalog,
  SkillHealth,
  CuratorFlag,
  DistillResult,
  DeleteResult,
  RunCatalogDto,
  RunVitalsDto,
  RunTimelineDto,
  RecapDto,
  RunDetailDto,
  RunListItem,
  RunSummary,
  ScheduledTaskCreateBody,
  ScheduledTaskDto,
  ScheduledTaskRunDto,
  ScheduledTaskUpdateBody,
  SeedsResponse,
  SkillCandidate,
  SkillEvaluateResult,
  SkillPromoteResult,
  SpawnDetail,
  SpawnSummary,
  SuggestDraft,
  SuggestPrimaryResult,
  TemplateInfo,
  UsageSummary,
  UserFact,
} from "./client.types";

export type { CollectionOut, EmbeddingStatus };

// Configurable for desktop (Tauri) builds; empty = same-origin relative URLs.
export const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "").replace(/\/+$/, "");
const BASE = `${API_BASE}/api/v1`;

export class ApiError extends Error {
  status: number;
  /** The parsed `detail` payload, when the server sent a STRUCTURED one.
   *
   * The evolve spend gate answers 409 with an object (code, last_attempt_id, reason,
   * est_tokens…) that the confirmation dialog renders verbatim — the frontend must not
   * invent the explanation. Stringifying it into `message` would throw those fields away
   * and leave the UI with "[object Object]". */
  detail?: unknown;
  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
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
    let structured: unknown;
    try {
      const body = await resp.json();
      // Prefer FastAPI's { detail }, but fall back to a plain-string error body.
      if (typeof body === "string") detail = body;
      else if (body.detail != null && typeof body.detail === "object") {
        // a structured detail (e.g. the evolve spend gate) — keep the object, and give
        // `message` something readable rather than "[object Object]"
        structured = body.detail;
        detail = (body.detail as { code?: string }).code ?? detail;
      } else detail = body.detail ?? detail;
    } catch {
      // keep default
    }
    throw new ApiError(detail, resp.status, structured);
  }
  return (await resp.json()) as T;
}

/** One leaf of GET /brain/tree.
 *
 * 🔴 `sensitive` is a RENDERING HINT (lock badge), NOT protection: the payload still
 * carries the fact's text in `label`, and `/brain/entry` still returns it in `excerpt`.
 * It is `boolean | null`-shaped on the wire because the DB column is nullable and the
 * backend coerces NULL to true (fail-closed) — never widen this to a bare `boolean` by
 * copying UserFact's over-narrow declaration. Profile leaves only; other kinds omit it
 * rather than claim a flag that was never checked. */
export interface BrainLeaf {
  kind: "material" | "learning" | "profile" | "note";
  ref: string;
  label: string;
  /** legacy DISPLAY string (e.g. "auto" / "投喂"), NOT the audit record */
  provenance: string | null;
  confidence: number | null;
  usage_count: number;
  last_used_at: string | null;
  last_used_ref: string | null;
  value: number;
  children?: BrainLeaf[];
  category?: string | null;
  tags?: string[];
  /** P1 temporal fields — emitted for profile/learning leaves since the P1 round. */
  valid_from?: string | null;
  superseded_by?: number | null;
  /** D2 — profile leaves only. See the type-level note above. */
  sensitive?: boolean;
}
export interface BrainBranch { kind: BrainLeaf["kind"]; label: string; children: BrainLeaf[]; }
/** One node of GET /brain/graph.
 *
 * `kind` stays a loose string on purpose: besides the four entry kinds the graph also
 * emits synthetic "ghost" | "tag" | "self" nodes, which are built as bare literals and
 * therefore carry ONLY the five base fields — every per-kind extra below is optional
 * for that reason. `sensitive` is a rendering hint, not protection (see BrainLeaf). */
export interface GraphNodeDto {
  id: string;
  ref: string;
  kind: string;
  label: string;
  val: number;
  /** profile nodes */
  source?: string | null;
  confidence?: number | null;
  sensitive?: boolean;
  /** profile + learning nodes (P1 temporal) */
  superseded_by?: number | null;
  /** D4 — every REAL node (profile/material/learning/note); absent on the synthetic
   * ghost/tag/self nodes, hence optional. `val` already folds usage into a render
   * size; these are the raw values the activity timeline needs. */
  usage_count?: number;
  last_used_at?: string | null;
  /** D4 — profile + learning only. Facts read their JSON column; learnings synthesize
   * `{source_kind, source_ref}` because that pair IS their provenance. */
  provenance_record?: Record<string, unknown> | null;
  /** F1 — profile + learning ONLY: when the belief took effect. */
  valid_from?: string | null;
  /** F1 — note + material ONLY: when the row came into existence.
   *
   * 🔴 Two names, never interchangeable. Notes and materials have no superseded_by and
   * no valid_from column at all, so they have no belief lifetime — only an existence.
   * Because both fields are optional, reading the wrong one for a kind typechecks
   * cleanly and silently yields undefined (= "never filter this"), which is why the
   * exact key sets in tests/server/test_brain_payload_shape.py assert `==` per kind:
   * that test, not the compiler, is what holds these two apart. */
  created_at?: string | null;
}
export interface GraphLinkDto { source: string; target: string; type: string }
export interface BrainGraphDto { nodes: GraphNodeDto[]; links: GraphLinkDto[] }
export interface BrainEntry {
  kind: string;
  ref: string;
  label: string;
  /** legacy DISPLAY string; the audit payload is `provenance_record` */
  provenance: string | null;
  confidence: number | null;
  /** 🔴 the entry's full text — returned for sensitive facts too (see BrainLeaf) */
  excerpt: string;
  usage_count: number;
  last_used_at: string | null;
  last_used_ref: string | null;
  /** P1 fields the backend has emitted since that round */
  valid_from?: string | null;
  superseded_by?: number | null;
  /** shape differs per kind: the raw fact JSON for profile, a synthesized
   *  {source_kind, source_ref} for learning, null for material */
  provenance_record?: Record<string, unknown> | null;
  /** D2 — profile entries only */
  sensitive?: boolean;
}

export interface BrainUsageEventDto {
  kind: string;
  ref_key: string;
  used_at: string | null;
  used_ref: string | null;
}
/** D5 — GET /brain/usage-events. The honesty fields are backend-supplied by design;
 * see getBrainUsageEvents. */
export interface BrainUsageEventsDto {
  /** the kinds that actually produce events — NOT the kinds the graph draws */
  covered_kinds: string[];
  /** human-readable coverage + truncation caveat; render it, do not re-derive it */
  coverage_note: string;
  /** events before this point were pruned by retention, not absent because unused */
  window_start: string | null;
  applied_limit: number;
  /** true ⇒ the OLDEST part of the requested window is missing from `events` */
  truncated: boolean;
  events: BrainUsageEventDto[];
}

/** The evolve spend gate's 409 payload (批1 P5). Every field is supplied by the BACKEND
 * so the dialog states facts rather than guesses — same rule as the brain usage-event
 * coverage note. `est_tokens` is neither a ceiling nor a reliable floor; see the copy. */
export interface EvolveRepeatRefusal {
  code: "same_corpus_as_failed_attempt";
  last_attempt_id: number;
  last_outcome: string;
  last_reason: string;
  new_runs_since: number;
  /** Still emitted, still the over-stating number; the dialog no longer shows it. */
  est_tokens: number | null;
  est_is_lower_bound: boolean;
  /** What the dialog shows now: the derived dispatch ceiling. Null on an estimate that
   * predates it, in which case no figure is shown at all rather than a misleading one. */
  est_dispatches_max: number | null;
}

/** One row of GET /brain/proposals — the Tier-2 human gate (F2).
 *
 * 🔴 `new_excerpt` / `old_excerpt` are present ONLY on the LIST response. accept/dismiss
 * return the same row WITHOUT them, so patching a cached list row with an action's
 * response silently deletes the excerpts. Refetch instead — which is required anyway,
 * because accepting one proposal auto-dismisses its siblings server-side with no signal
 * in the response.
 *
 * 🔴 Excerpts are TRUNCATED to 200 chars while `provenance.content` / `new_array` are
 * not, so diffing one against the other invents deletions at the tail of any long value. */
export interface MemoryProposalDto {
  id: number;
  kind:
    | "supersede_suspect"
    | "append_suspect"
    | "delete_suspect"
    | "edit_high_conf_suspect"
    | "preference_overwrite_suspect";
  table_name: string;
  new_id: number | null;
  /** 0 is a SENTINEL meaning "nothing existed before" (append_suspect), not row 0 */
  old_id: number | null;
  reason: string | null;
  status: string;
  provenance: Record<string, unknown> | null;
  created_at: string | null;
  resolved_at: string | null;
  new_excerpt?: string | null;
  old_excerpt?: string | null;
}

import type { ServerConversation } from "../lib/sessionPersistence";

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),
  /** Gate item ⑦ — which conversations exist. The SERVER is the source of
   *  truth for this; localStorage cannot be, because the packaged app gets a
   *  fresh origin (and so a fresh, empty store) on every launch. */
  listConversations: () => request<ServerConversation[]>("/conversations"),
  getBrainTree: () => request<{ branches: BrainBranch[] }>("/brain/tree"),
  getBrainEntry: (kind: string, ref: string) =>
    request<BrainEntry>(`/brain/entry/${kind}/${encodeURIComponent(ref)}`),
  getBrainGraph: () => request<BrainGraphDto>("/brain/graph"),
  /** D5 — the per-use event log behind the activity timeline. `covered_kinds` and
   * `coverage_note` come from the BACKEND on purpose: the log covers material /
   * learning / note only (profile facts are never recorded as usage events), and a
   * truncated page is missing its OLDEST end, which would otherwise render as a quiet
   * period. Show the note; do not re-derive coverage on the client. */
  listMemoryProposals: (opts?: { status?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (opts?.status) q.set("status", opts.status);
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    if (opts?.offset != null) q.set("offset", String(opts.offset));
    const qs = q.toString();
    return request<MemoryProposalDto[]>(`/brain/proposals${qs ? `?${qs}` : ""}`);
  },
  /** Materialize a proposal. NOTE the server also auto-dismisses sibling proposals for
   * the same (kind, table, old_id, conversation) — so callers must REFETCH the list,
   * never patch the single row. */
  acceptMemoryProposal: (id: number) =>
    request<MemoryProposalDto>(`/brain/proposals/${id}/accept`, { method: "POST" }),
  dismissMemoryProposal: (id: number) =>
    request<MemoryProposalDto>(`/brain/proposals/${id}/dismiss`, { method: "POST" }),
  getBrainUsageEvents: (opts?: { since?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.since) q.set("since", opts.since);
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return request<BrainUsageEventsDto>(`/brain/usage-events${qs ? `?${qs}` : ""}`);
  },
  /** D3 — restore a superseded entry to active. Only `profile` and `learning` entries
   * can be superseded at all; any other kind is refused with 422 by the server. */
  undoSupersede: (kind: "profile" | "learning", ref: string) =>
    request<{ kind: string; ref: string; superseded_by: null }>("/brain/undo-supersede", {
      method: "POST",
      body: JSON.stringify({ kind, ref }),
    }),
  listNotes: () => request<NoteDto[]>("/brain/notes"),
  getNote: (id: number) => request<NoteDto>(`/brain/notes/${id}`),
  createNote: (b: { title: string; content?: string; tags?: string[] }) =>
    request<NoteDto>("/brain/notes", { method: "POST", body: JSON.stringify(b) }),
  updateNote: (id: number, b: { title?: string; content?: string; tags?: string[] }) =>
    request<NoteDto>(`/brain/notes/${id}`, { method: "PATCH", body: JSON.stringify(b) }),
  deleteNote: (id: number) => request<{ deleted: boolean }>(`/brain/notes/${id}`, { method: "DELETE" }),
  suggestNoteLinks: (id: number) => request<NoteSuggestDto>(`/brain/notes/${id}/suggest`, { method: "POST" }),
  generateNotes: (topic: string) =>
    request<{ created: NoteDto[] }>("/brain/notes/generate", { method: "POST", body: JSON.stringify({ topic }) }),
  listSpawns: () => request<SpawnSummary[]>("/spawns"),
  draftSpawn: (description: string) =>
    request<SuggestDraft>("/spawns/draft", { method: "POST", body: JSON.stringify({ description }) }),
  createSpawn: (body: {
    name: string;
    domain: string;
    capabilities: string[];
    persona_role?: string | null;
    persona_tone?: string | null;
    seed_refs?: string[];
    equipment?: { toolsets: string[]; skills: string[] };
  }) =>
    request<SpawnDetail>("/spawns", { method: "POST", body: JSON.stringify(body) }),
  /** Browse / search the 249 persona seed identities. */
  getSeeds: (query?: string, limit = 40, offset = 0) => {
    const qs = new URLSearchParams();
    if (query) qs.set("query", query);
    qs.set("limit", String(limit));
    qs.set("offset", String(offset));
    return request<SeedsResponse>(`/seeds?${qs.toString()}`);
  },
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
  /** Why stored secrets cannot be read. Verdict key + counts; never plaintext. */
  getCryptoHealth: () => request<CryptoHealth>("/settings/crypto-health"),
  /** Whether the server gates on a bearer token + (localhost-only) the token itself. */
  getAccessToken: () => request<AccessTokenInfo>("/settings/access-token"),
  /** Rotate the access token (localhost-gated). Returns the freshly minted token. */
  resetAccessToken: () =>
    request<{ token: string }>("/settings/access-token/reset", { method: "POST" }),
  /** Generate/rotate the dedicated MCP-server token (localhost-gated). Returns it once. */
  generateMcpToken: () =>
    request<{ token: string }>("/settings/mcp-token/generate", { method: "POST" }),
  listProviders: () => request<ProviderOption[]>("/settings/providers"),
  listSearchProviders: () => request<string[]>("/settings/search-providers"),
  /** What THIS machine's text recognition can read, asked at request time.
   * Never a constant: the set grows with the OS version, so a list baked
   * into the UI would promise the user what their system may not do. */
  /** Search the brain through the SAME pipeline a spawn reads it with.
   *  `ranking` names the pipeline that actually ran — rerank is lexical
   *  overlap, not semantics, so the UI must never render a relevance score. */
  searchBrain: (q: string, limit = 20) =>
    request<{
      query: string;
      ranking: "lexical" | "hybrid";
      truncated: boolean;
      results: { kind: string; ref: string; title: string; snippet: string }[];
    }>(`/brain/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  listOcrLanguages: () =>
    request<{ available: string[]; max_selectable: number; platform_supported: boolean }>(
      "/settings/ocr-languages"),
  updateSettings: (body: Partial<AppSettings>) =>
    request<AppSettings>("/settings", { method: "PUT", body: JSON.stringify(body) }),
  getRegistry: () => request<RegistryCatalog>("/registry"),
  /** PC-5 on-demand skill health probe (bounded storage + script-runnability check on the
   * server; never executes skill code). Mirrors checkMcpHealth. */
  checkSkillHealth: (key: string) =>
    request<SkillHealth>(`/registry/skills/${encodeURIComponent(key)}/health`, { method: "POST" }),
  updateEquipment: (id: number, body: { toolsets: string[]; skills: string[] }) =>
    request<SpawnDetail>(`/spawns/${id}/equipment`, { method: "PUT", body: JSON.stringify(body) }),
  listFacts: () => request<UserFact[]>("/facts"),
  addFact: (body: { content: string; sensitive?: boolean }) =>
    request<UserFact>("/facts", { method: "POST", body: JSON.stringify(body) }),
  updateFact: (id: number, body: { content?: string; sensitive?: boolean }) =>
    request<UserFact>(`/facts/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteFact: (id: number) => request<void>(`/facts/${id}`, { method: "DELETE" }),
  /** Generate a concise thread title from the first user message + optional first reply.
   *  conversationId (S3-M3 fold-in) lets the backend usage ledger attribute the
   *  titler call to its conversation — optional on the wire (TitleIn). */
  generateTitle: (firstMessage: string, firstReply?: string, conversationId?: string): Promise<{ title: string }> =>
    request<{ title: string }>("/orchestrator/title", {
      method: "POST",
      body: JSON.stringify({
        first_message: firstMessage,
        first_reply: firstReply,
        ...(conversationId ? { conversation_id: conversationId } : {}),
      }),
    }),
  getRun: (id: number) => request<RunDetailDto>(`/runs/${id}`),
  getRuns: (spawnId?: number, limit = 50, conversationId?: string) => {
    const qs = new URLSearchParams();
    if (spawnId != null) qs.set("spawn_id", String(spawnId));
    if (conversationId != null) qs.set("conversation_id", conversationId);
    qs.set("limit", String(limit));
    return request<RunListItem[]>(`/runs?${qs.toString()}`);
  },
  /** Aggregates for the evaluation-summary charts. */
  getRunsSummary: () => request<RunSummary>("/runs/summary"),
  /** Per-spawn RED aggregate + fleet rollup, worst-first (diagnosis dashboard). */
  getRunCatalog: (range: string) => request<RunCatalogDto>(`/runs/catalog?range=${range}`),
  /** Deterministic threshold-rule findings, severity-sorted (diagnosis dashboard). */
  getRunAnomalies: (range: string) => request<AnomalyDto[]>(`/runs/anomalies?range=${range}`),
  /** Bucketed run-rate + error overlay + duration heatmap (diagnosis vitals). */
  getRunVitals: (range: string) => request<RunVitalsDto>(`/runs/vitals?range=${range}`),
  /** Per-spawn severity bands over time (anomaly timeline). */
  getRunTimeline: (range: string) => request<RunTimelineDto>(`/runs/timeline?range=${range}`),
  /** This conversation's recap timeline — runs + growth events merged, newest first. */
  getConversationRecap: (id: string) => request<RecapDto>(`/conversations/${id}/recap`),
  /** S3-M3: cumulative token/USD usage for one conversation (spawn runs + ledger scopes). */
  getConversationUsage: (id: string) => request<ConversationUsage>(`/conversations/${id}/usage`),
  /** S3-M3: fleet-wide usage summary — provider×model×scope rows + daily series + 未计入. */
  getUsageSummary: (range: "24h" | "7d" | "30d") =>
    request<UsageSummary>(`/usage/summary?range=${range}`),
  // ── S3-M4 scheduled tasks: CRUD + pause/resume/fire-now + history ─────────────
  listScheduledTasks: () => request<ScheduledTaskDto[]>("/scheduled-tasks"),
  createScheduledTask: (body: ScheduledTaskCreateBody) =>
    request<ScheduledTaskDto>("/scheduled-tasks", { method: "POST", body: JSON.stringify(body) }),
  updateScheduledTask: (id: number, body: ScheduledTaskUpdateBody) =>
    request<ScheduledTaskDto>(`/scheduled-tasks/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  /** Deletes the task AND its history rows (FK cascade on the server). */
  deleteScheduledTask: (id: number) =>
    request<{ ok: boolean }>(`/scheduled-tasks/${id}`, { method: "DELETE" }),
  /** Manual pause — paused_reason stays null (non-null always means auto-pause). */
  pauseScheduledTask: (id: number) =>
    request<ScheduledTaskDto>(`/scheduled-tasks/${id}/pause`, { method: "POST" }),
  /** Clears failures/paused_reason; next_due recomputed forward. 409 over the enabled cap. */
  resumeScheduledTask: (id: number) =>
    request<ScheduledTaskDto>(`/scheduled-tasks/${id}/resume`, { method: "POST" }),
  /** 202 accepted; 409 when a run is already in flight (single-flight). */
  fireScheduledTaskNow: (id: number) =>
    request<{ status: string; task_id: number }>(`/scheduled-tasks/${id}/fire-now`, { method: "POST" }),
  /** Execution history, newest first; run_id links to RunReplay. */
  getScheduledTaskRuns: (id: number) =>
    request<ScheduledTaskRunDto[]>(`/scheduled-tasks/${id}/runs`),
  /** Manually redact one run's sensitive/bulky debug detail (system_prompt, injected_kb, ...). */
  redactRun: (id: number) => request<{ redacted: boolean }>(`/runs/${id}/redact`, { method: "POST" }),
  /** Cancel an in-flight run (S3-M1). 202 {ok} on cancel; 404 unknown; 409 already terminal. */
  cancelRun: (id: number) => request<{ ok: boolean }>(`/runs/${id}/cancel`, { method: "POST" }),
  /** Manually redact every run's sensitive/bulky debug detail. Returns the count touched. */
  redactAllRuns: () => request<{ redacted: number }>(`/runs/redact-all`, { method: "POST" }),
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
  // S2 evolution (spec §E7). The old sync propose was replaced by a background job:
  // GET the estimate, POST to enqueue (202), then review the resulting proposal in the inbox.
  getEvolveEstimate: (spawnId: number) =>
    request<EvolveEstimate>(`/spawns/${spawnId}/evolve/estimate`),
  /** POST the manual trigger. The server gates a click that would re-run a corpus which
   * already failed: it answers 409 with a structured detail, and only `force` proceeds.
   * The gate is fail-closed, so omitting force is the safe default, not a shortcut. */
  runEvolve: (spawnId: number, opts?: { force?: boolean }) =>
    request<EvolveEnqueued>(`/spawns/${spawnId}/evolve`, {
      method: "POST",
      body: JSON.stringify({ force: opts?.force ?? false }),
    }),
  getEvolutionProposals: (status?: string) =>
    request<ProposalListItem[]>(
      `/evolution/proposals${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
  getProposalDetail: (proposalId: number) =>
    request<ProposalDetail>(`/evolution/proposals/${proposalId}`),
  getEvolutionDiagnosis: (spawnId: number) =>
    request<SpawnDiagnosis>(`/spawns/${spawnId}/evolution/diagnosis`),
  refreshProposal: (proposalId: number) =>
    request<RefreshResult>(`/evolution/proposals/${proposalId}/refresh`, { method: "POST" }),
  confirmProposal: (proposalId: number) =>
    request<ConfirmResult>(`/evolution/proposals/${proposalId}/confirm`, { method: "POST" }),
  rejectProposal: (proposalId: number) =>
    request<ConfirmResult>(`/evolution/proposals/${proposalId}/reject`, { method: "POST" }),
  rollbackProposal: (proposalId: number) =>
    request<RollbackResult>(`/evolution/proposals/${proposalId}/rollback`, { method: "POST" }),
  listMcpServers: () =>
    request<
      Array<{
        id: number;
        label: string;
        status?: string;
        health_status?: string | null;
        last_error?: string | null;
        last_checked_at?: string | null;
      }>
    >("/mcp/servers"),
  /** PB-4 on-demand equipment health probe (bounded list_tools on the server side). */
  checkMcpHealth: (id: number) =>
    request<{
      id: number;
      label: string;
      transport: string;
      health_status: "ok" | "failing";
      last_checked_at: string | null;
      last_error: string | null;
      tool_count: number | null;
      proxy_source: string;
    }>(`/mcp/${id}/health`, { method: "POST" }),
  // ── Skill Forge: self-authored skills → observe → gate → promote ──────────────
  /** Package a SKILL.md into a candidate. 400 (surfaced as ApiError.message) on invalid. */
  forgeSkill: (body: {
    key: string;
    name: string;
    category: string;
    description: string;
    body: string;
    source?: string;
  }) => request<SkillCandidate>("/skills/forge", { method: "POST", body: JSON.stringify(body) }),
  listSkillCandidates: (status?: string) => {
    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    const q = qs.toString();
    return request<SkillCandidate[]>(`/skills/candidates${q ? `?${q}` : ""}`);
  },
  evaluateSkillCandidate: (id: number, body: { target_spawn_id: number; min_samples?: number }) =>
    request<SkillEvaluateResult>(`/skills/candidates/${id}/evaluate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  promoteSkillCandidate: (id: number) =>
    request<SkillPromoteResult>(`/skills/candidates/${id}/promote`, { method: "POST" }),
  rejectSkillCandidate: (id: number) =>
    request<{ ok: boolean }>(`/skills/candidates/${id}/reject`, { method: "POST" }),
  // ── Curator (Slice 3): post-promotion usage/quality signals + human retire ──────
  getCuratorReview: () => request<CuratorFlag[]>("/skills/curator/review"),
  /** Human-confirmed retire: unassigns the skill everywhere. 409 (ApiError) if not a promoted skill. */
  retireSkill: (key: string) =>
    request<{ ok: boolean; key?: string; unassigned?: number; reason?: string }>(
      "/skills/curator/retire",
      { method: "POST", body: JSON.stringify({ key }) },
    ),
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
  // ── Second Brain: shared knowledge collections (layer A) ──────────────────────
  listCollections: () => request<CollectionOut[]>("/collections"),
  createCollection: (name: string, description?: string) =>
    request<CollectionOut>("/collections", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  patchCollection: (id: number, patch: { name?: string; description?: string }) =>
    request<CollectionOut>(`/collections/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteCollection: (id: number) => request<{ deleted: boolean; chunks_removed: number }>(`/collections/${id}`, { method: "DELETE" }),
  ingestCollection: (id: number, body: { source?: string; text?: string; url?: string }) =>
    request<IngestResult>(`/collections/${id}/ingest`, { method: "POST", body: JSON.stringify(body) }),
  /** Multipart upload — mirrors ingestKnowledgeFile: build the fetch by hand so
   *  the browser sets its own multipart Content-Type (with boundary) rather
   *  than the JSON header `request` applies by default. */
  ingestCollectionFile: async (id: number, file: File): Promise<IngestResult> => {
    const token = useAuthStore.getState().token;
    const form = new FormData();
    form.append("file", file);
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const resp = await fetch(`${BASE}/collections/${id}/ingest`, {
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
  getCollectionKnowledge: (id: number) => request<KnowledgeSource[]>(`/collections/${id}/knowledge`),
  deleteCollectionSource: (id: number, source: string) =>
    request<{ deleted: number }>(
      `/collections/${id}/knowledge?source=${encodeURIComponent(source)}`,
      { method: "DELETE" },
    ),
  bindCollection: (spawnId: number, cid: number) =>
    request<{ bound: boolean }>(`/spawns/${spawnId}/collections/${cid}`, { method: "PUT" }),
  unbindCollection: (spawnId: number, cid: number) =>
    request<{ bound: boolean }>(`/spawns/${spawnId}/collections/${cid}`, { method: "DELETE" }),
  // ── Embedding ops: active provider status, backfill, local-model download ─────
  embeddingStatus: () => request<EmbeddingStatus>("/embedding/status"),
  reindexEmbeddings: () =>
    request<{ started: boolean; reason?: string }>("/embedding/reindex", { method: "POST" }),
  downloadEmbeddingModel: () =>
    request<{ started: boolean; status: EmbeddingStatus["local_model"] }>("/embedding/download-model", { method: "POST" }),
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

/** Dynamic model catalog for a saved provider config. `refresh=true` forces a
 *  live re-fetch from the provider (doubles as an API-key sanity check). */
export const fetchProviderModels = (id: number, refresh = false) =>
  request<ModelListResult>(
    `/settings/provider-configs/${id}/models${refresh ? "?refresh=true" : ""}`,
  );

export const getCatalog = () =>
  request<CatalogEntry[]>("/settings/catalog");

// ── Conversation actions: distill (harvest spawn chats) + delete ──────────────

/** Distill a conversation's spawn chats into memory. Returns how many were distilled. */
export const distillConversation = (id: string) =>
  request<DistillResult>(`/conversations/${id}/distill`, { method: "POST" });

/** Permanently delete a conversation + its rows. Returns per-table delete counts. */
export const deleteConversation = (id: string) =>
  request<DeleteResult>(`/conversations/${id}`, { method: "DELETE" });

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

// ── Provider connectivity probe (Provider-P4) ─────────────────────────────────

/** Tri-state connectivity probe result. `reachable_no_list` means HTTP answered
 *  but no usable model list — chat may still work. */
export interface HealthResult {
  state: "reachable_models" | "reachable_no_list" | "unreachable";
  latency_ms: number | null;
  detail: string | null;
  /** Naive-UTC ISO (no timezone suffix) — append "Z" before parsing. */
  last_health_at: string | null;
}

/** Probe a saved provider config's connectivity. Fires only on explicit
 *  Settings interactions (spec D4: no background polling). */
export const probeProviderHealth = (id: number) =>
  request<HealthResult>(`/settings/provider-configs/${id}/health`, {
    method: "POST",
  });
