/**
 * Which spawns THIS conversation has dispatched to.
 *
 * Decision (a): the Active Spawns list is scoped to the session by DISPATCH, not
 * by "has a direct chat open" (which is what `hasActiveChat` meant and what the
 * list used before). The two are different questions — a spawn you opened a
 * chat with once, months ago, is not part of this session's work; a spawn this
 * conversation routed to is, whether or not you ever chatted with it directly.
 *
 * Derived from runs rather than tracked in the client: a Run row carries both
 * conversation_id and spawn_id, so the answer already exists server-side and is
 * correct across reloads. A client-side tally would start empty every time the
 * window reopened and would quietly under-report — the kind of wrong that looks
 * like "nothing happened yet".
 */
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';

/** How many runs to look back over. A conversation with more dispatches than
 *  this is already far past the point where a sidebar list is the right way to
 *  see them, and the honest consequence (older dispatches drop off) beats an
 *  unbounded query on every thread switch. */
const LOOKBACK = 100;

export function useDispatchedSpawns(conversationId: string | undefined | null) {
  const [ids, setIds] = useState<Set<number>>(new Set());

  const refresh = useCallback(async () => {
    if (!conversationId) {
      setIds(new Set());
      return;
    }
    try {
      const runs = await api.getRuns(undefined, LOOKBACK, conversationId);
      setIds(new Set(runs.map((r) => r.spawn_id).filter((x): x is number => x != null)));
    } catch {
      // A failed lookup must not empty the list: showing "no spawns" because a
      // request failed is a lie about the session, and the previous answer is
      // the better guess. Left as-is deliberately.
    }
  }, [conversationId]);

  useEffect(() => { void refresh(); }, [refresh]);

  return { dispatchedSpawnIds: ids, refreshDispatched: refresh };
}
