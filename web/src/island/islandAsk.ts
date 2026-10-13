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

/** The action kinds the island has words for (locales/island.ts `ask`). Any other is a kind from
 *  the permission layer (0.1.61 §A11), whose line is the card's own question. */
const KNOWN_ACTIONS = new Set(['browser_site', 'desktop_app', 'desktop_risky', 'mac_shortcut',
  'mac_script', 'desktop_takeover']);

/** Whether the island has words of its own for this card's kind. A command, a write and a schedule always have; an action card
 *  only for the kinds above. */
export function knowsKind(card: PendingCard): boolean {
  const f = card.frame;
  return f.type !== 'propose_action' || KNOWN_ACTIONS.has(str(f.kind));
}

/** The model's own reason for an action card (§A4), trimmed; '' when it gave none. For a kind the island has no words for it is the
 *  question, ahead of the line; for one it has, it is shown as "Arslan says". Never the only description: the line stays. */
export function askWhy(card: PendingCard): string {
  return card.frame.type === 'propose_action' ? str(card.frame.why) : '';
}

/** The one line that says WHAT exactly: the command, the file, the cadence, the app. For an action kind the island has no words for,
 *  the server's own words: the frame's title (a title of spaces is none), else the target. */
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
      if (!KNOWN_ACTIONS.has(str(f.kind)) && str(f.title)) return str(f.title);
      const first = str(f.detail).split('\n').find((l) => l.trim()) ?? '';
      return [str(f.target), f.kind === 'mac_script' ? first.trim() : ''].filter(Boolean).join(' · ');
    }
    default: return '';
  }
}

/** The island's note under a card it will not answer, keyed by `locales/island.ts`. The card's permission kind decides: a takeover, a step outside
 *  the sandbox, a system setting, a new ability, another agent's settings, code that is downloaded or decoded first and another machine each say what
 *  they are; "may delete, send or pay" is for money, send, destructive and a risky step in an app, which all do one of those. A kind the island does
 *  not know gets the neutral line — never a wrong risk. A card with no kind, or the plain command kind, is read by what holds it, as before 0.1.61. */
const HELD_NOTES = { takeover: 'heldTakeover', outside: 'heldOutside', system: 'heldSystem', capability: 'heldCapability',
  other_agent: 'heldOtherAgent', opaque: 'heldOpaque', remote: 'heldRemote' } as const;
const RISKY_KINDS = new Set(['money', 'send', 'destructive', 'app_risky']);
export function heldNoteKey(card: PendingCard):
    'riskyNote' | 'heldGeneric' | (typeof HELD_NOTES)[keyof typeof HELD_NOTES] {
  const f = card.frame;
  const kind = typeof f.perm_kind === 'string' ? f.perm_kind : '';
  if (Object.prototype.hasOwnProperty.call(HELD_NOTES, kind)) return HELD_NOTES[kind as keyof typeof HELD_NOTES];
  if (RISKY_KINDS.has(kind)) return 'riskyNote';
  if (!kind || kind === 'command') {
    if (!kind && f.kind === 'desktop_risky') return 'riskyNote';
    if (f.remote_host) return 'heldRemote';
    if (f.sandbox === 'outside' || f.sandbox === 'retry') return 'heldOutside';
  }
  return 'heldGeneric';
}

/** The one line the island adds under an AppleScript card it will answer (final review, M3): the script is asked as the app it names (`kind` app, the
 *  bundle id), so the "Allow for this task" it takes also lets Arslan Hands look at and act in that app for the task (spec §A5: one list of allowed
 *  apps, shared by Hands and osascript). The chat card says so in `grant.mac_script`; null for every other card. */
export function alsoAllowsKey(card: PendingCard): 'scriptAlsoHands' | null {
  const f = card.frame;
  return f.type === 'propose_action' && f.kind === 'mac_script' && f.perm_kind === 'app' ? 'scriptAlsoHands' : null;
}

/** What Allow says here (0.1.61 §A4). The island answers a card once only — "for this task" on a
 *  card whose first choice is that (the server holds it there, approvals.FIRST_CHOICE_ONLY) — so
 *  on a card that offers more it says which. */
export function allowKey(card: PendingCard): 'allow' | 'allowOnce' | 'allowTask' {
  const options = Array.isArray(card.frame.options) ? card.frame.options : [];
  if (options[0] === 'task') return 'allowTask';
  return options.length > 1 ? 'allowOnce' : 'allow';
}

/** Seconds until the card runs out unanswered (never a refusal), never below zero. */
export function secondsLeft(card: PendingCard, nowMs: number): number {
  return Math.max(0, Math.round(card.expires_at - nowMs / 1000));
}

export function mmss(sec: number): string {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}
