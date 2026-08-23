/**
 * Filtering what you ALREADY have (Capability Library).
 *
 * The Discover tab already has a search box, and it searches GitHub — things
 * you do not have yet. There was no way to search the other direction, so on a
 * page listing dozens of toolsets, skills and servers the only way to find one
 * was to scroll. That is the gap this closes; it is deliberately not a second
 * discovery surface.
 *
 * Matching lives here rather than inline in three components because the three
 * lists have different shapes and the RULES should not: one query, matched the
 * same way everywhere, and testable without rendering anything.
 *
 * The nested case is the one that earns its keep. Someone looking for
 * `web_search` is looking for a TOOL, and tools live inside toolsets — so a
 * query that matches only an inner tool still surfaces its toolset, and says
 * which tool it matched on. A card appearing with no visible reason is a filter
 * the user stops trusting.
 */

export interface Searchable {
  key: string;
  name?: string | null;
  description?: string | null;
}

/** Normalised query. Empty (or whitespace) means "no filter", not "match nothing". */
export function normalizeQuery(query: string | null | undefined): string {
  return (query ?? "").trim().toLowerCase();
}

function haystack(item: Searchable): string {
  return [item.key, item.name ?? "", item.description ?? ""].join("\n").toLowerCase();
}

/** Does this item match on its own fields? */
export function matches(item: Searchable, query: string): boolean {
  const q = normalizeQuery(query);
  // Explicitness, not behaviour: `"anything".includes("")` is already true, so
  // deleting this line changes nothing and no test can tell the difference.
  // It stays because a reader should not have to know that to see that an empty
  // query means "no filter" — which IS pinned, in capability-search.test.ts.
  if (!q) return true;
  return haystack(item).includes(q);
}

/**
 * Names of the nested tools a query matched, for a toolset whose own fields did
 * not. Empty when the toolset matched on its own right — the caller shows the
 * "matched via" line only when it explains something the user cannot already see.
 */
export function matchedChildren(
  item: Searchable & { tools?: Searchable[] },
  query: string,
): string[] {
  const q = normalizeQuery(query);
  if (!q || matches(item, q)) return [];
  return (item.tools ?? [])
    .filter((child) => matches(child, q))
    .map((child) => child.name ?? child.key);
}

/** Keep items matching on their own fields OR through a nested tool. */
export function filterItems<T extends Searchable & { tools?: Searchable[] }>(
  items: readonly T[],
  query: string,
): T[] {
  const q = normalizeQuery(query);
  if (!q) return [...items];
  return items.filter((it) => matches(it, q) || matchedChildren(it, q).length > 0);
}
