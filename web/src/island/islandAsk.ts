/**
 * What the island shows for one waiting card (0.1.55 Island v2), as pure functions.
 * Whether the island may APPROVE it is the server's call (`island_ok`); this only
 * decides the words: which kind of ask, and the one line that identifies it.
 */
import type { PendingCard } from './feed';

/** The ask kind the island's strings are keyed by. */
export function askKind(card: PendingCard): string {
  const f = card.frame;
  switch (f.type) {
    case 'propose_run_command': return 'run_command';
    case 'propose_workspace_write': return 'workspace_write';
    case 'propose_schedule': return 'schedule';
    case 'propose_action': return typeof f.kind === 'string' ? f.kind : 'other';
    default: return 'other';
  }
}

const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '');

/** The one line that says WHAT exactly: the command, the file, the cadence, the app. */
export function askLine(card: PendingCard): string {
  const f = card.frame;
  switch (f.type) {
    case 'propose_run_command': {
      const host = str(f.remote_host);
      return host ? `${host} · ${str(f.pretty)}` : str(f.pretty);
    }
    case 'propose_workspace_write': return str(f.path) || str(f.workspace);
    case 'propose_schedule': return [str(f.name), str(f.when)].filter(Boolean).join(' · ');
    case 'propose_action': {
      const first = str(f.detail).split('\n').find((l) => l.trim()) ?? '';
      return [str(f.target), f.kind === 'mac_script' ? first.trim() : ''].filter(Boolean).join(' · ');
    }
    default: return '';
  }
}

/** Seconds until the card is declined by itself, never below zero. */
export function secondsLeft(card: PendingCard, nowMs: number): number {
  return Math.max(0, Math.round(card.expires_at - nowMs / 1000));
}

export function mmss(sec: number): string {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}
