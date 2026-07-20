import { describe, expect, it } from "vitest";

import {
  MAX_CHAIN,
  chainOf,
  hiddenAt,
  successorId,
  supersedeLinks,
  supersededAt,
} from "../temporal";

type N = Parameters<typeof successorId>[0];

const fact = (id: number, o: Partial<N> = {}): N =>
  ({ id: `fact:${id}`, kind: "profile", valid_from: null, ...o }) as N;
const learning = (id: number, o: Partial<N> = {}): N =>
  ({ id: `learning:${id}`, kind: "learning", valid_from: null, ...o }) as N;
const note = (id: number, o: Partial<N> = {}): N =>
  ({ id: `note:${id}`, kind: "note", created_at: null, ...o }) as N;

const T = (s: string) => `${s}T00:00:00.000000Z`;

describe("successorId — prefix comes from the node's own id, never its kind", () => {
  it("resolves a FACT successor (id prefix 'fact:', kind 'profile')", () => {
    // 🔴 This is the whole point of the test. A fact node's id is `fact:N` while its
    // kind is `profile` (server/api/brain.py:261). Building `${kind}:${superseded_by}`
    // yields "profile:2", which matches no node — and because supersedeLinks drops
    // links to unknown nodes, the bug is SILENT and kind-asymmetric: learning chains
    // render fine, fact chains just never appear.
    expect(successorId(fact(1, { superseded_by: 2 }))).toBe("fact:2");
  });

  it("resolves a LEARNING successor — the kind-based bug would pass this one", () => {
    expect(successorId(learning(1, { superseded_by: 9 }))).toBe("learning:9");
  });

  it("returns null when nothing supersedes it", () => {
    expect(successorId(fact(1))).toBeNull();
    expect(successorId(note(1))).toBeNull();
  });
});

describe("supersededAt — derived, and null whenever it cannot be trusted", () => {
  const index = (ns: N[]) => new Map(ns.map((n) => [n.id, n]));

  it("returns the successor's valid_from when it is trustworthy", () => {
    const a = fact(1, { superseded_by: 2, valid_from: T("2024-01-01") });
    const b = fact(2, { valid_from: T("2025-01-01") });
    expect(supersededAt(a, index([a, b]))).toBe(T("2025-01-01"));
  });

  it("is null when the successor is not in the node set (dangling pointer)", () => {
    const a = fact(1, { superseded_by: 99, valid_from: T("2024-01-01") });
    expect(supersededAt(a, index([a]))).toBeNull();
  });

  it("is null when the successor's own valid_from is null — never invent a time", () => {
    const a = fact(1, { superseded_by: 2, valid_from: T("2024-01-01") });
    const b = fact(2, { valid_from: null });
    expect(supersededAt(a, index([a, b]))).toBeNull();
  });

  it("is null when the successor predates the predecessor (proposal-accept inversion)", () => {
    // server/api/brain.py:901-905 supersedes a PRE-EXISTING row whose valid_from was
    // set at propose time, so it can be older than the row it replaces. Reporting it
    // would render a belief that died before it was born.
    const a = fact(1, { superseded_by: 2, valid_from: T("2025-01-01") });
    const b = fact(2, { valid_from: T("2024-01-01") });
    expect(supersededAt(a, index([a, b]))).toBeNull();
  });

  it("is null when successor and predecessor share an instant", () => {
    const a = fact(1, { superseded_by: 2, valid_from: T("2025-01-01") });
    const b = fact(2, { valid_from: T("2025-01-01") });
    expect(supersededAt(a, index([a, b]))).toBeNull();
  });

  it("is null once the pointer is cleared — undo must erase the derived time", () => {
    // nail 1. undo_supersede (memory_temporal.py:110-112) only clears superseded_by;
    // there is no other state to clean up, and this pins that there never is.
    const b = fact(2, { valid_from: T("2025-01-01") });
    const before = fact(1, { superseded_by: 2, valid_from: T("2024-01-01") });
    const after = fact(1, { superseded_by: null, valid_from: T("2024-01-01") });
    // BOTH directions in one body: an implementation that keys off a field that does
    // not exist returns null for every input and would pass the "after" half alone.
    expect(supersededAt(before, index([before, b]))).toBe(T("2025-01-01"));
    expect(supersededAt(after, index([after, b]))).toBeNull();
  });

  it("compares instants, not strings", () => {
    // _iso() has two output shapes (brain.py:56-77): "...07.000000Z" and a preserved
    // offset. This fixture is built so string order and time order DISAGREE, which is
    // the only way the assertion can see the difference:
    //   successor "T11:00:00+09:00" = 02:00Z — EARLIER than the predecessor's 04:00Z,
    //   so the inversion guard must fire and the answer is null;
    //   but as text "T11..." > "T04...", so a lexicographic compare concludes the
    //   successor is later, skips the guard, and reports a bogus end time.
    // (A fixture where both orders agree passes against BOTH implementations — it
    // asserts a value the bug also produces, and proves nothing.)
    const a = fact(1, { superseded_by: 2, valid_from: "2025-01-01T04:00:00.000000Z" });
    const b = fact(2, { valid_from: "2025-01-01T11:00:00+09:00" });
    expect(supersededAt(a, index([a, b]))).toBeNull();
  });
});

describe("supersedeLinks", () => {
  it("emits one directed edge per resolvable pointer", () => {
    const ns = [fact(1, { superseded_by: 2 }), fact(2), learning(3)];
    expect(supersedeLinks(ns)).toEqual([
      { source: "fact:1", target: "fact:2", type: "supersede" },
    ]);
  });

  it("emits NOTHING for a dangling pointer — no phantom target", () => {
    // d3 forceLink throws "node not found" on an endpoint outside the node set.
    expect(supersedeLinks([fact(1, { superseded_by: 404 })])).toEqual([]);
  });
});

describe("chainOf", () => {
  it("walks both directions, oldest first", () => {
    const ns = [fact(1, { superseded_by: 2 }), fact(2, { superseded_by: 3 }), fact(3)];
    expect(chainOf("fact:2", ns).ids).toEqual(["fact:1", "fact:2", "fact:3"]);
  });

  it("returns a single-element chain for an entry with no supersede relation", () => {
    expect(chainOf("fact:1", [fact(1)]).ids).toEqual(["fact:1"]);
  });

  it("terminates on a cycle", () => {
    const ns = [fact(1, { superseded_by: 2 }), fact(2, { superseded_by: 1 })];
    const out = chainOf("fact:1", ns);
    expect(new Set(out.ids).size).toBe(out.ids.length); // no id repeats
    expect(out.ids.length).toBeLessThanOrEqual(MAX_CHAIN);
    // a cycle is not a truncation: the walk ended because it came back round, and
    // reporting "truncated" there would claim entries exist that do not
    expect(out.truncated).toBe(false);
  });

  it("caps a very long chain", () => {
    const ns = Array.from({ length: 200 }, (_, i) =>
      fact(i + 1, i + 1 < 200 ? { superseded_by: i + 2 } : {}));
    const out = chainOf("fact:1", ns);
    expect(out.ids.length).toBe(MAX_CHAIN);
    // and it SAYS it was cut — a real flag from the walk, not inferred from the
    // length, which cannot tell a complete 64-chain from a cut one
    expect(out.truncated).toBe(true);
  });
});

describe("hiddenAt — the as-of predicate", () => {
  const ids = (s: Set<string>) => [...s].sort();

  it("hides nothing when the slider is at home", () => {
    expect(hiddenAt([fact(1, { valid_from: T("2030-01-01") })], [], null).size).toBe(0);
  });

  it("hides a belief that had not taken effect yet", () => {
    const ns = [fact(1, { valid_from: T("2025-06-01") })];
    expect(ids(hiddenAt(ns, [], T("2025-01-01")))).toEqual(["fact:1"]);
  });

  it("SHOWS a belief whose valid_from is exactly T (boundary is inclusive)", () => {
    // pins `<=` against `<`; every other fixture in this file has T != valid_from
    const ns = [fact(1, { valid_from: T("2025-01-01") })];
    expect(hiddenAt(ns, [], T("2025-01-01")).size).toBe(0);
  });

  it("SHOWS a belief with a null valid_from at every T", () => {
    // models.py:148 — NULL = 自古有效. The 0032 backfill leaves NULL where created_at
    // was also NULL (_0032_brain_temporal.py:66), so these rows exist in the wild.
    const ns = [fact(1, { valid_from: null })];
    expect(hiddenAt(ns, [], T("1990-01-01")).size).toBe(0);
  });

  it("hides a belief that was already superseded at T", () => {
    const ns = [
      fact(1, { superseded_by: 2, valid_from: T("2024-01-01") }),
      fact(2, { valid_from: T("2025-01-01") }),
    ];
    expect(ids(hiddenAt(ns, [], T("2026-01-01")))).toEqual(["fact:1"]);
  });

  it("SHOWS a superseded belief whose end time is unknown", () => {
    // not knowing when it stopped is not the same as knowing it had stopped
    const ns = [
      fact(1, { superseded_by: 2, valid_from: T("2024-01-01") }),
      fact(2, { valid_from: null }),
    ];
    expect(hiddenAt(ns, [], T("2026-01-01")).size).toBe(0);
  });

  it("filters notes and materials on created_at, not valid_from", () => {
    const ns = [note(1, { created_at: T("2025-06-01") })];
    expect(ids(hiddenAt(ns, [], T("2025-01-01")))).toEqual(["note:1"]);
  });

  it("hides a tag once every one of its sources is hidden, and not before", () => {
    // otherwise no past instant is ever empty: tags are derived from TODAY's
    // notes.tags / facts.category, so a tag made last week would decorate a
    // picture of last year.
    const ns = [
      fact(1, { valid_from: T("2020-01-01") }),
      fact(2, { valid_from: T("2025-06-01") }),
      { id: "tag:x", kind: "tag" } as N,
    ];
    const links = [
      { source: "fact:1", target: "tag:x", type: "tag" },
      { source: "fact:2", target: "tag:x", type: "tag" },
      // 🔴 The hub edge the server sends for EVERY tag (brain.py:349-354). Omitting it
      // is what let the first implementation ship broken: `self` is never hidden, so
      // counting the hub as a source made `every(hidden)` false for every tag in every
      // real payload — no tag could ever be hidden, while this test said otherwise.
      { source: "self", target: "tag:x", type: "hub" },
    ];
    expect(ids(hiddenAt(ns, links, T("2021-01-01")))).toEqual(["fact:2"]);
    expect(ids(hiddenAt(ns, links, T("2010-01-01")))).toEqual(
      ["fact:1", "fact:2", "tag:x"]);
  });

  it("hides a ghost with its source note", () => {
    const ns = [note(1, { created_at: T("2025-06-01") }), { id: "ghost:z", kind: "ghost" } as N];
    const links = [{ source: "note:1", target: "ghost:z", type: "link" }];
    expect(ids(hiddenAt(ns, links, T("2025-01-01")))).toEqual(["ghost:z", "note:1"]);
  });

  it("never hides 「你」, even if the payload ever gives it a timestamp", () => {
    // self is the viewer, not a piece of remembered data.
    // The fixture carries a valid_from ON PURPOSE. Today's backend builds self as a
    // five-key literal with no time (brain.py:357), so a timeless fixture would be
    // invisible to this assertion — deleting the guard entirely would still leave
    // self shown, and the test would pass against the bug. Giving it a time is what
    // makes the guard the only thing keeping 「你」 on screen.
    const ns = [{ id: "self", kind: "self", valid_from: T("2025-01-01") } as N];
    expect(hiddenAt(ns, [], T("1990-01-01")).size).toBe(0);
  });
});

describe("chainOf — incompleteness it must not hide", () => {
  it("reports merged ancestors when two rows point at the same successor", () => {
    // fact dedup can merge duplicates into one survivor, making the genealogy a DAG.
    // Only one branch is walked, so the panel has to say the other exists rather than
    // present one line as the whole story.
    const ns = [
      fact(1, { superseded_by: 3 }),
      fact(2, { superseded_by: 3 }),
      fact(3),
    ];
    expect(chainOf("fact:3", ns).mergedAncestors).toBe(true);
  });

  it("does NOT report merged ancestors on a plain linear chain", () => {
    const ns = [fact(1, { superseded_by: 2 }), fact(2)];
    expect(chainOf("fact:2", ns).mergedAncestors).toBe(false);
  });

  it("does NOT report truncation on a chain that exactly fits", () => {
    const ns = Array.from({ length: MAX_CHAIN }, (_, i) =>
      fact(i + 1, i + 1 < MAX_CHAIN ? { superseded_by: i + 2 } : {}));
    const out = chainOf("fact:1", ns);
    expect(out.ids.length).toBe(MAX_CHAIN);
    expect(out.truncated).toBe(false);   // complete — nothing was dropped
  });
});
