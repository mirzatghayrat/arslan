/**
 * F1 — belief-time derivation for the brain graph.
 *
 * 🔴 WHAT THIS CANNOT DO. There is no `superseded_at` column anywhere in the schema.
 * A belief's END is never recorded; it is DERIVED here from its successor's
 * `valid_from`, and only when that derivation is trustworthy. Everything downstream
 * of this file is a filter over rows that STILL EXIST — it is not a history.
 * Specifically, none of these leave a trace and none can be shown:
 *
 *   - hard deletes (memory.py:392-405, fact_dedup.py:152/:181, brain.py:745,
 *     note_service.py:95, collections.py:80/:147) — the row is simply gone
 *   - in-place content edits (memory.py:378-386, note_service.py:78-88) — a past
 *     instant renders TODAY's text under an old timestamp
 *   - accepting a delete_suspect nulls superseded_by (brain.py:727-740), erasing the
 *     record that a supersede ever happened
 *   - mark_stale (memory_executors._mark_stale_tier1) sets provenance.stale, which now
 *     takes the fact out of injection and recall (memory.list_facts) and is shown in the
 *     entry panel — but it is a CURRENT-state flag, not a temporal one: `marked_at` is
 *     recorded and still read by nothing, so a graph filtered to a past instant shows
 *     today's mark, not the mark as it stood then
 *
 * The UI says so on the control itself, not only here — see BrainAsOfSlider.
 */

export type TemporalNode = {
  id: string;
  kind: string;
  superseded_by?: number | null;
  /** facts + learnings only: when the belief took effect */
  valid_from?: string | null;
  /** notes + materials only: when the row came into existence */
  created_at?: string | null;
};

export type TemporalLink = { source: string; target: string; type: string };

/** Display cap for a rendered genealogy.
 *
 * Deliberately NOT described as "the maximum chain length". memory_temporal's
 * `_MAX_CHAIN` (:28) is a give-up bound inside a cycle GUARD — exhausting it lets the
 * write through (:78), so nothing in the system caps a real chain at any length. This
 * number only bounds what we draw; anything past it is truncated, and the panel says
 * so. */
export const MAX_CHAIN = 64;

/** Instant of an ISO string, or null. Never compare these lexicographically:
 * `_iso` (brain.py:56-77) emits both "...07.000000Z" and a preserved "+08:00" offset,
 * and '+' < '.' < 'Z' in ASCII, so string order contradicts time order across those
 * shapes and even within one (a second-precision stamp sorts after a microsecond one
 * in the same second). */
export function parseTime(s: string | null | undefined): number | null {
  if (!s) return null;
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t;
}

/** When a node came into being, whichever clock its kind carries. */
export function startedAt(n: TemporalNode): number | null {
  return parseTime(n.valid_from ?? n.created_at);
}

/**
 * The node id of whatever superseded this one, or null.
 *
 * 🔴 The prefix comes from the node's OWN id, never from `kind`. A fact node's id is
 * `fact:N` while its kind is `profile` (brain.py:261) — `${kind}:${superseded_by}`
 * would yield "profile:N", matching nothing. Because supersedeLinks drops edges to
 * unknown nodes, that bug is silent and kind-asymmetric: learning chains would render
 * and fact chains would simply never appear.
 */
export function successorId(n: TemporalNode): string | null {
  if (n.superseded_by == null) return null;
  const prefix = n.id.split(":")[0];
  return `${prefix}:${n.superseded_by}`;
}

/**
 * The DERIVED instant this belief stopped being current, as an ISO string — or null,
 * meaning "unknown", which the UI must render as 未知 rather than as a time.
 *
 * Null in four cases, all of them real:
 *   - nothing supersedes it
 *   - the successor is not in the node set (dangling pointer)
 *   - the successor's own valid_from is null
 *   - the successor does not postdate the predecessor. Accepting a supersede_suspect
 *     (brain.py:901-905) supersedes a row that already existed at propose time, so its
 *     valid_from can be older than the row it replaces. Reporting that would draw a
 *     belief dying before it was born.
 */
export function supersededAt(
  n: TemporalNode,
  byId: Map<string, TemporalNode>,
): string | null {
  const sid = successorId(n);
  if (!sid) return null;
  const succ = byId.get(sid);
  if (!succ?.valid_from) return null;
  const end = parseTime(succ.valid_from);
  const start = parseTime(n.valid_from);
  if (end == null) return null;
  if (start != null && end <= start) return null;
  return succ.valid_from;
}

/** Generic so callers keep their own richer node type (label, val, …) — narrowing to
 * TemporalNode here would erase those fields for every consumer of the index. */
export function indexById<T extends TemporalNode>(nodes: T[]): Map<string, T> {
  return new Map(nodes.map((n) => [n.id, n]));
}

/** Directed predecessor→successor edges. Built off an index rather than a per-node
 * scan so this stays linear on a node set with no server-side LIMIT. */
export function supersedeLinks(nodes: TemporalNode[]): TemporalLink[] {
  const byId = indexById(nodes);
  const out: TemporalLink[] = [];
  for (const n of nodes) {
    const sid = successorId(n);
    // a pointer to a row that is gone (hard-deleted, or simply not in this payload)
    // must NOT produce an edge: d3 forceLink throws on an endpoint outside the set
    if (sid && byId.has(sid)) out.push({ source: n.id, target: sid, type: "supersede" });
  }
  return out;
}

/**
 * The genealogy containing `id`, oldest first.
 *
 * Returns `truncated` as a REAL flag rather than letting the caller infer it from the
 * length. A chain of exactly MAX_CHAIN may be complete or may be cut — those are
 * different facts, and `length >= MAX_CHAIN` calls a complete one truncated while
 * `length > MAX_CHAIN` (impossible, since the walk caps) never reports anything at all.
 *
 * `mergedAncestors` flags the other incompleteness: two rows can point at the same
 * successor (dedup merging duplicates into one survivor), which makes the genealogy a
 * DAG rather than a chain. Only one branch is walked, so the panel must say the rest
 * exists instead of presenting one line as the whole story.
 */
export function chainOf(
  id: string,
  nodes: TemporalNode[],
): { ids: string[]; truncated: boolean; mergedAncestors: boolean } {
  const byId = indexById(nodes);
  const predecessor = new Map<string, string>();
  const predecessorCount = new Map<string, number>();
  for (const n of nodes) {
    const sid = successorId(n);
    if (!sid) continue;
    predecessor.set(sid, n.id);
    predecessorCount.set(sid, (predecessorCount.get(sid) ?? 0) + 1);
  }

  let truncated = false;
  const back: string[] = [];
  const seen = new Set<string>([id]);
  let cur = predecessor.get(id);
  while (cur && !seen.has(cur)) {
    if (back.length + 1 >= MAX_CHAIN) { truncated = true; break; }
    seen.add(cur);
    back.unshift(cur);
    cur = predecessor.get(cur);
  }

  const forward: string[] = [];
  let node = byId.get(id);
  while (node) {
    const sid = successorId(node);
    if (!sid || seen.has(sid)) break;      // end of chain, or a cycle
    if (back.length + forward.length + 1 >= MAX_CHAIN) { truncated = true; break; }
    seen.add(sid);
    forward.push(sid);
    node = byId.get(sid);
  }

  const ids = [...back, id, ...forward];
  const mergedAncestors = ids.some((x) => (predecessorCount.get(x) ?? 0) > 1);
  return { ids, truncated, mergedAncestors };
}

/**
 * Ids to hide at instant `asOf`. Null asOf ⇒ empty set (the slider's home position
 * changes nothing at all).
 *
 * Returns ids rather than a filtered node list on purpose: the caller keeps the d3
 * node and link arrays IDENTICAL and only changes how they are painted. Removing
 * nodes would (a) make forceLink throw on the edges left pointing at them and
 * (b) rebuild the whole simulation on every slider frame, discarding every computed
 * x/y so the graph collapses to the centre and re-anneals as you drag.
 */
export function hiddenAt(
  nodes: TemporalNode[],
  links: TemporalLink[],
  asOf: string | null,
): Set<string> {
  const hidden = new Set<string>();
  const t = parseTime(asOf);
  if (t == null) return hidden;

  const byId = indexById(nodes);
  for (const n of nodes) {
    // 「你」 is the viewer, not a piece of remembered data — it has no birthday and
    // must not blink out. tag/ghost are decided below, from their sources.
    if (n.kind === "self" || n.kind === "tag" || n.kind === "ghost") continue;

    const start = startedAt(n);
    if (start != null && start > t) { hidden.add(n.id); continue; }

    // An unknown end is NOT an end: not knowing when a belief stopped is different
    // from knowing that it had stopped, so it stays visible (labelled 未知).
    const end = parseTime(supersededAt(n, byId));
    if (end != null && end <= t) hidden.add(n.id);
  }

  // Synthetic nodes follow their sources. Without this, no past instant is ever
  // empty: tags come from TODAY's notes.tags / facts.category and ghosts from
  // today's [[links]], so both would decorate a picture of a time before they existed.
  const sources = new Map<string, string[]>();
  for (const l of links) {
    // 🔴 The 「你」 hub edge is NOT a source. brain.py:349-354 gives every tag a
    // `self -> tag` hub link unconditionally, and `self` is never hidden — so counting
    // it as a source makes `every(hidden)` false for EVERY tag in EVERY real payload,
    // and no tag is ever hidden. (The first version of this code did exactly that; the
    // unit test missed it because its fixture omitted the hub edge the server always
    // sends. The fixture now includes it.)
    if (l.type === "hub") continue;
    const target = byId.get(l.target);
    if (target && (target.kind === "tag" || target.kind === "ghost")) {
      (sources.get(l.target) ?? sources.set(l.target, []).get(l.target)!).push(l.source);
    }
  }
  for (const [id, srcs] of sources) {
    if (srcs.length > 0 && srcs.every((s) => hidden.has(s))) hidden.add(id);
  }

  return hidden;
}
