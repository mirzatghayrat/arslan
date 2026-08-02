/**
 * The dirty checks, tested as behaviour rather than as source text.
 *
 * 🔴 Why this file exists: the first version of these lived inline in each
 * component and was asserted only through the source — "does the file contain
 * setConfirmingClose(true)". Two mutations proved that worthless. `dirty =
 * false && …` and deleting the ternary from App both left the string in the
 * file and stayed GREEN. A confirm dialog that never fires is
 * indistinguishable from one that works, so the green was the dangerous kind.
 *
 * Third time this session the same lesson landed: a grep hit proves a string is
 * in a file, not that a user experiences anything.
 *
 * Every case is tested from BOTH sides. A predicate stuck at `true` is as
 * broken as one stuck at `false` — it would make every editor ask before
 * closing, training the user to dismiss the question without reading it.
 */
import { describe, it, expect } from "vitest";

import {
  createSpawnDirty, gapFillDirty, noteDirty, sameKeys, spawnStudioDirty,
} from "../lib/dirty";

describe("spawnStudioDirty", () => {
  const empty = { name: "", description: "", domain: "",
                  toolsets: new Set<string>(), skills: new Set<string>(), baseline: null };

  it("create: a blank form is clean", () => {
    expect(spawnStudioDirty({ ...empty, mode: "create" })).toBe(false);
  });

  it("create: one typed character is dirty", () => {
    expect(spawnStudioDirty({ ...empty, mode: "create", name: "x" })).toBe(true);
  });

  it("create: whitespace alone is NOT dirty", () => {
    // Discriminating: `Boolean(name)` instead of `name.trim()` would make a
    // stray space enough to trigger the prompt.
    expect(spawnStudioDirty({ ...empty, mode: "create", name: "   " })).toBe(false);
  });

  it("edit: unchanged equipment is clean", () => {
    const base = { toolsets: new Set(["a"]), skills: new Set(["s"]) };
    expect(spawnStudioDirty({
      ...empty, mode: "edit", baseline: base,
      toolsets: new Set(["a"]), skills: new Set(["s"]),
    })).toBe(false);
  });

  it("edit: equipping one more tool is dirty", () => {
    const base = { toolsets: new Set(["a"]), skills: new Set<string>() };
    expect(spawnStudioDirty({
      ...empty, mode: "edit", baseline: base,
      toolsets: new Set(["a", "b"]), skills: new Set(),
    })).toBe(true);
  });

  it("edit: swapping one tool for another is dirty even though the count matches", () => {
    // Discriminating: comparing `size` alone would call this clean.
    const base = { toolsets: new Set(["a"]), skills: new Set<string>() };
    expect(spawnStudioDirty({
      ...empty, mode: "edit", baseline: base,
      toolsets: new Set(["b"]), skills: new Set(),
    })).toBe(true);
  });

  it("edit: nothing loaded yet is clean", () => {
    expect(spawnStudioDirty({ ...empty, mode: "edit", toolsets: new Set(["a"]) })).toBe(false);
  });

  it("edit: the CREATE fields do not make it dirty", () => {
    // They are never populated from the loaded spawn — treating them as a diff
    // was the bug the type checker caught in the first implementation.
    const base = { toolsets: new Set<string>(), skills: new Set<string>() };
    expect(spawnStudioDirty({
      ...empty, mode: "edit", baseline: base, name: "typed", description: "typed",
    })).toBe(false);
  });
});

describe("createSpawnDirty", () => {
  it("blank is clean, any field is dirty", () => {
    expect(createSpawnDirty("", "", "")).toBe(false);
    expect(createSpawnDirty("n", "", "")).toBe(true);
    expect(createSpawnDirty("", "d", "")).toBe(true);
    expect(createSpawnDirty("", "", "desc")).toBe(true);
  });

  it("whitespace is clean", () => {
    expect(createSpawnDirty(" ", "\t", "\n")).toBe(false);
  });
});

describe("gapFillDirty", () => {
  const clean = { ref: "", busy: false, hasEvalResult: false, hasSkillDraft: false,
                  mcpDraft: { command: "", args: "", url: "" } };

  it("an untouched modal is clean", () => {
    expect(gapFillDirty(clean)).toBe(false);
  });

  it("in-flight work counts as dirty", () => {
    // Closing mid-step orphans the call — the reason `busy` is in here at all.
    expect(gapFillDirty({ ...clean, busy: true })).toBe(true);
  });

  it("a draft awaiting consent counts as dirty", () => {
    // It is a paid-for result the user has not accepted yet; losing it means
    // paying for the evaluation again.
    expect(gapFillDirty({ ...clean, hasEvalResult: true })).toBe(true);
    expect(gapFillDirty({ ...clean, hasSkillDraft: true })).toBe(true);
  });

  it("a half-filled MCP draft counts", () => {
    expect(gapFillDirty({ ...clean, mcpDraft: { command: "npx", args: "", url: "" } })).toBe(true);
  });
});

describe("noteDirty", () => {
  const loaded = { title: "T", content: "C", tags: ["a", "b"] };

  it("an unmodified note is clean", () => {
    expect(noteDirty({ loaded, title: "T", content: "C", tags: ["a", "b"] })).toBe(false);
  });

  it("edited body is dirty", () => {
    expect(noteDirty({ loaded, title: "T", content: "C!", tags: ["a", "b"] })).toBe(true);
  });

  it("a changed tag is dirty even with the same count", () => {
    expect(noteDirty({ loaded, title: "T", content: "C", tags: ["a", "z"] })).toBe(true);
  });

  it("nothing loaded is clean", () => {
    expect(noteDirty({ loaded: null, title: "x", content: "y", tags: [] })).toBe(false);
  });
});

describe("sameKeys", () => {
  it("is order-independent but content-sensitive", () => {
    expect(sameKeys(new Set(["a", "b"]), new Set(["b", "a"]))).toBe(true);
    expect(sameKeys(new Set(["a"]), new Set(["b"]))).toBe(false);
    expect(sameKeys(new Set(["a"]), new Set(["a", "b"]))).toBe(false);
  });
});
