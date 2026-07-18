/**
 * roster_invite frame builders — the single place that decides whether an invite
 * carries `origin: 'invite_card'`.
 *
 * The BUG2 contract is cross-layer and easy to break by accident: the backend only
 * emits the honest "joined, but nothing was queued — @ them" notice when the client
 * marks the accept as coming from a CARD (server/ws/arslan.py, roster_invite handler).
 * A card promised a consequence; a Ledger pull promised only membership. Constructing
 * the frames here (instead of inline in App.tsx) keeps that distinction testable — a
 * refactor that "normalizes" the two shapes has to delete a builder, not just edit a
 * literal, and the guard test below notices.
 */

export type RosterInviteFrame = {
  type: 'roster_invite';
  spawn_id: number | string;
  origin?: 'invite_card';
};

/** Accept of an Arslan-proposed card (invite card / staffing picker). */
export function cardAcceptInvite(spawnId: number | string): RosterInviteFrame {
  return { type: 'roster_invite', spawn_id: spawnId, origin: 'invite_card' };
}

/** Manual pull from the Ledger — membership only, no promised consequence. */
export function ledgerInvite(spawnId: number | string): RosterInviteFrame {
  return { type: 'roster_invite', spawn_id: spawnId };
}
