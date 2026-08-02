/**
 * "Is this editor holding something the user would mind losing?"
 *
 * 🔴 These live here as PURE FUNCTIONS because the first version of them lived
 * inline in each component and was only ever asserted through the source: the
 * tests checked that `setConfirmingClose(true)` appeared in the file. Two
 * mutations proved that worthless — `dirty = false && …` and deleting the
 * ternary from App both left the string in place and stayed green. A confirm
 * dialog that never fires looks exactly like one that works.
 *
 * A dirty check is a pure function of form state, so it can be tested as one.
 *
 * Each editor keeps its OWN function rather than sharing one, because they
 * genuinely differ: SpawnStudio diffs equipment sets against a load-time
 * snapshot, NoteEditor diffs against the loaded note, the create forms have no
 * baseline at all (empty is clean), and GapFill additionally counts drafts
 * awaiting consent and in-flight work.
 */

/** Two sets hold the same keys. */
export function sameKeys(a: Set<string>, b: Set<string>): boolean {
  return a.size === b.size && [...a].every((k) => b.has(k));
}

/** SpawnStudio. Create mode has no baseline; edit mode diffs the equipment. */
export function spawnStudioDirty(args: {
  mode: "create" | "edit";
  name: string;
  description: string;
  domain: string;
  toolsets: Set<string>;
  skills: Set<string>;
  baseline: { toolsets: Set<string>; skills: Set<string> } | null;
}): boolean {
  if (args.mode === "create") {
    return Boolean(args.name.trim() || args.description.trim() || args.domain.trim()
      || args.toolsets.size || args.skills.size);
  }
  if (!args.baseline) return false;          // nothing loaded = nothing to lose
  return !sameKeys(args.toolsets, args.baseline.toolsets)
    || !sameKeys(args.skills, args.baseline.skills);
}

/** The create-spawn modal. The emoji has a default and is deliberately NOT
 *  counted — counting it would make every open dirty. */
export function createSpawnDirty(name: string, domain: string, description: string): boolean {
  return Boolean(name.trim() || domain.trim() || description.trim());
}

/** GapFillModal. `busy` counts: closing mid-step orphans an in-flight call, and
 *  a draft under review is a paid-for result the user has not consented to yet. */
export function gapFillDirty(args: {
  ref: string;
  busy: boolean;
  hasEvalResult: boolean;
  hasSkillDraft: boolean;
  mcpDraft: { command: string; args: string; url: string };
}): boolean {
  return Boolean(args.ref.trim() || args.busy || args.hasEvalResult || args.hasSkillDraft
    || args.mcpDraft.command.trim() || args.mcpDraft.args.trim() || args.mcpDraft.url.trim());
}

/** NoteEditor. Baseline is the loaded note; nothing loaded means nothing to lose. */
export function noteDirty(args: {
  loaded: { title: string; content: string; tags: string[] } | null;
  title: string;
  content: string;
  tags: string[];
}): boolean {
  if (!args.loaded) return false;
  const same = (a: string[], b: string[]) =>
    a.length === b.length && a.every((t, i) => t === b[i]);
  return args.title !== args.loaded.title
    || args.content !== args.loaded.content
    || !same(args.tags, args.loaded.tags);
}
