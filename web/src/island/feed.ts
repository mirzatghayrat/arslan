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
