/**
 * Resolve a spawn's display name by id, tolerant of the string-vs-number id
 * mismatch that bites when crossing the UI/data boundary.
 *
 * The data-layer SpawnSummary has a numeric `id`; the UI `Spawn` adapter
 * stringifies it (`String(s.id)`). `propose_invite.spawn_id` is always numeric.
 * Comparing a string id to a numeric id with `===` is silently always false and
 * tsc won't catch it (find's predicate accepts string===number). Normalizing
 * both sides to string before comparing makes the lookup correct regardless of
 * which list (numeric-id SpawnSummary or string-id UI Spawn) is passed in.
 */
export function resolveSpawnName(
  spawns: ReadonlyArray<{ id: number | string; name: string }>,
  spawnId: number | string,
): string | undefined {
  const target = String(spawnId);
  return spawns.find((s) => String(s.id) === target)?.name;
}
