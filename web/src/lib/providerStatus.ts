/**
 * What a provider's dot means — one question, one answer.
 *
 * The old model had two tiers: a /models "connectivity" probe (green) and a
 * separate "deep test" (a real chat). That split was the defect. Listing models
 * answers a question nobody asked: OpenRouter's model list is a PUBLIC endpoint
 * that returns 200 with no key at all, so a dead, capped or region-blocked key
 * still lit the dot green while every actual message failed.
 *
 * So there is now one question — *can this LLM answer a message?* — and the only
 * thing that may answer it is a real chat round-trip. Anything we have not
 * actually established reads as "untested", never as working.
 */

import type { ProviderConfig } from '../api/client.types';

export type ProviderStatus = 'ok' | 'failed' | 'untested' | 'testing';

export interface StatusView {
  status: ProviderStatus;
  /** Why it failed, in a sentence a non-engineer can act on. Null unless failed. */
  reason: string | null;
  /** When this verdict was formed (naive-UTC ISO); null when untested/testing. */
  at: string | null;
}

/** The in-session overlay: a test the user (or app launch) started just now. */
export interface LiveTest {
  state: 'idle' | 'testing' | 'ok' | 'failed';
  error?: string;
  at?: string | null;
}

type HealthFields = Pick<ProviderConfig, 'last_health' | 'last_health_at' | 'last_health_detail'>;

export function providerStatus(config: HealthFields, live?: LiveTest): StatusView {
  // A test in flight outranks any stored verdict — it is about to replace it.
  if (live?.state === 'testing') return { status: 'testing', reason: null, at: null };

  // A result from this session is fresher than the row we were handed.
  if (live?.state === 'ok') return { status: 'ok', reason: null, at: live.at ?? null };
  if (live?.state === 'failed') {
    return { status: 'failed', reason: live.error ?? null, at: live.at ?? null };
  }

  const stored = config.last_health;
  if (stored === 'ok') return { status: 'ok', reason: null, at: config.last_health_at ?? null };
  if (stored === 'failed') {
    return {
      status: 'failed',
      reason: config.last_health_detail ?? null,
      at: config.last_health_at ?? null,
    };
  }

  // null, "", or a word retired by migration 0043 (a row written by an older
  // build, or one the migration missed). Fail OPEN to "untested": claiming a
  // verdict we cannot vouch for is the whole defect we are removing. The
  // backend's _last_health_ok makes the same call for the same reason.
  return { status: 'untested', reason: null, at: null };
}

/** Can the user send a message with this one right now, as far as we know? */
export function isUsable(view: StatusView): boolean {
  // "untested" counts as usable: a fresh install has tested nothing, and
  // refusing to route anywhere would be worse than trying. Only a verdict we
  // actually have — a failed test — takes a model out of play.
  return view.status !== 'failed';
}
