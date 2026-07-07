import { describe, expect, it } from "vitest";
import { activeMention, filterRoster, insertMention } from "./mentions";

describe("activeMention", () => {
  it("detects an @token at the caret (start of input)", () => {
    expect(activeMention("@de", 3)).toEqual({ at: 0, query: "de" });
  });
  it("detects an @token after whitespace", () => {
    expect(activeMention("hi @de", 6)).toEqual({ at: 3, query: "de" });
  });
  it("detects a bare @ right after typing it", () => {
    expect(activeMention("hi @", 4)).toEqual({ at: 3, query: "" });
  });
  it("does NOT trigger on an email-like a@b (no leading boundary)", () => {
    expect(activeMention("mail a@b", 8)).toBeNull();
  });
  it("closes once a space follows the token", () => {
    expect(activeMention("@deck ", 6)).toBeNull();
  });
  it("uses the caret, not end of string", () => {
    expect(activeMention("@deck more", 3)).toEqual({ at: 0, query: "de" });
  });
});

describe("filterRoster", () => {
  const r = [
    { spawnId: 1, spawnName: "Deck Master" },
    { spawnId: 2, spawnName: "Data Analyst" },
    { spawnId: 3, spawnName: "Research" },
    { spawnId: 4, spawnName: null },
  ];
  it("empty query returns all named members in order", () => {
    expect(filterRoster(r, "").map((m) => m.spawnId)).toEqual([1, 2, 3]);
  });
  it("starts-with ranks before contains, case-insensitive", () => {
    // "a" starts Data/Analyst? starts: none start with 'a'; contains: Deck M[a]ster, D[a]ta, Rese[a]rch
    expect(filterRoster(r, "d").map((m) => m.spawnId)).toEqual([1, 2]); // Deck, Data start with d
    expect(filterRoster(r, "de").map((m) => m.spawnId)).toEqual([1]);  // only Deck
  });
  it("drops members without a name", () => {
    expect(filterRoster(r, "").some((m) => m.spawnId === 4)).toBe(false);
  });
});

describe("insertMention", () => {
  it("replaces the @token with `@name ` and returns the new caret", () => {
    const tok = activeMention("hi @de", 6)!;
    const out = insertMention("hi @de", tok, 6, "Deck Master");
    expect(out.value).toBe("hi @Deck Master ");
    expect(out.caret).toBe(out.value.length);
  });
  it("preserves text after the caret", () => {
    const tok = activeMention("a @d b", 4)!;
    const out = insertMention("a @d b", tok, 4, "Deck");
    expect(out.value).toBe("a @Deck  b");
  });
});
