/**
 * The island's one data source: GET /api/v1/island/feed (0.1.51 I1).
 *
 * The island is its own page in its own window, so it does not load the app's
 * API client (and the 2.5 MB bundle that comes with it). Same origin as the
 * app, same bearer token: the shell injects it as window.__ARSLAN_TOKEN__.
 */

export type WorkKind = 'turn' | 'job' | 'scheduled';

export interface PlanItem {
  text: string | null;
  status: string;
}

export interface Activity {
  id: number;
  conversation_id: string | null;
  kind: WorkKind;
  title: string | null;
  started_at: number;
  step: { tool: string; target: string | null; at: number } | null;
  plan: { items: PlanItem[]; done: number; total: number } | null;
  /** 0.1.55: set for a background job, so the island can stop it. */
  job_id?: string | null;
  /** Hands v2 §6.6: the window the work last looked at, small (JPEG, base64); memory only. */
  thumb?: string | null;
}

/** Hands v2 §6.3-6.4: what a borrow or takeover is doing right now. */
export interface HandsLine {
  borrow: 'waiting' | 'borrowing' | null;
  takeover: { active: boolean; paused: boolean; remaining_s: number } | null;
}

/** One card waiting for the user (GET /api/v1/approvals/pending, 0.1.55). */
export interface PendingCard {
  call_id: string;
  conversation_id: string;
  frame: Record<string, unknown> & { type: string };
  opened_at: number;
  expires_at: number;
  /** The server's rule (approvals.island_may_answer): false = risky, answer it in Arslan. */
  island_ok: boolean;
}

export interface FeedEvent {
  id: number;
  kind: string;
  conversation_id: string | null;
  outcome: 'ok' | 'error' | 'needs_review' | 'cancelled' | null;
  task_id: number | null;
  at: number;
  title: string | null;
  summary: string | null;
  work: WorkKind | null;
}

export interface Feed {
  cursor: number;
  awaiting: number;
  awaiting_conversations: string[];
  active: Activity[];
  events: FeedEvent[];
  enabled: boolean;
  hands?: HandsLine | null;
}

declare global {
  interface Window {
    __ARSLAN_TOKEN__?: string;
  }
}

// The app's auth store keeps the token under this key (stores/authStore.ts);
// same origin, so a plain browser in dev can reuse it.
const STORED_TOKEN = 'arslan_token';

function token(): string | null {
  const injected = window.__ARSLAN_TOKEN__;
  if (typeof injected === 'string' && injected.trim()) return injected.trim();
  try {
    return localStorage.getItem(STORED_TOKEN) || null;
  } catch {
    return null;
  }
}

export async function fetchFeed(after: number | null, signal?: AbortSignal): Promise<Feed> {
  const headers: Record<string, string> = {};
  const t = token();
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(`/api/v1/island/feed?after=${after ?? 0}`, { headers, signal, cache: 'no-store' });
  if (!res.ok) throw new Error(`island feed ${res.status}`);
  return (await res.json()) as Feed;
}

/** Stop every Arslan Hands action now (0.1.53): kills the command in flight and
 * makes the jobs running now refuse further Hands calls. */
export async function stopHands(): Promise<boolean> {
  const headers: Record<string, string> = {};
  const t = token();
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch('/api/v1/hands/stop', { method: 'POST', headers, cache: 'no-store' });
  return res.ok;
}

function authHeaders(): Record<string, string> {
  const t = token();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** Every card waiting for the user, oldest first (0.1.55 Island v2). */
export async function fetchPending(signal?: AbortSignal): Promise<PendingCard[]> {
  const res = await fetch('/api/v1/approvals/pending', { headers: authHeaders(), signal, cache: 'no-store' });
  if (!res.ok) throw new Error(`pending ${res.status}`);
  const body: unknown = await res.json();
  if (!Array.isArray(body)) throw new Error('pending: not a list');
  return body.filter((c): c is PendingCard => !!c && typeof c === 'object'
    && typeof (c as PendingCard).call_id === 'string' && typeof (c as PendingCard).frame?.type === 'string');
}

/** Answer one card from the island. The server refuses to APPROVE a risky one (403). */
export async function answerCard(callId: string, approve: boolean): Promise<boolean> {
  const res = await fetch(`/api/v1/approvals/${encodeURIComponent(callId)}/answer`, {
    method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ approve, source: 'island' }),
  });
  return res.ok;
}

/** Stop one background job (the island's Stop on a job). */
export async function stopJob(jobId: string): Promise<boolean> {
  const res = await fetch(`/api/v1/background-jobs/${encodeURIComponent(jobId)}/stop`, {
    method: 'POST', headers: authHeaders(),
  });
  return res.ok;
}

async function post(path: string): Promise<boolean> {
  const res = await fetch(`/api/v1${path}`, { method: 'POST', headers: authHeaders(), cache: 'no-store' });
  if (!res.ok) return false;
  const body = (await res.json().catch(() => ({}))) as { ok?: boolean };
  return body.ok !== false;
}

/** A borrow waits for the user to pause typing (§6.3): borrow now, or not this time. */
export const answerBorrow = (answer: 'now' | 'skip') => post(`/hands/borrow/${answer}`);
/** A paused takeover (§6.4): let it go on, or take the screen back. */
export const continueTakeover = () => post('/hands/takeover/continue');
export const endTakeover = () => post('/hands/takeover/end');
