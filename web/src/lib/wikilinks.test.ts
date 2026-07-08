import { describe, expect, it } from "vitest";
import { activeWikilink, insertWikilink } from "./wikilinks";

describe("activeWikilink", () => {
  it("detects an open [[ token before the caret (end of string)", () => {
    expect(activeWikilink("see [[材", 7)).toEqual({ at: 4, query: "材" });
    expect(activeWikilink("see [[A]] done", 14)).toBeNull(); // closed
    expect(activeWikilink("plain", 5)).toBeNull();
  });
  it("detects a bare [[ right after typing it", () => {
    expect(activeWikilink("hi [[", 5)).toEqual({ at: 3, query: "" });
  });
  it("closes once ]] follows the token", () => {
    expect(activeWikilink("[[deck]] ", 9)).toBeNull();
  });
  it("uses the caret, not end of string", () => {
    expect(activeWikilink("[[deck]] more", 5)).toEqual({ at: 0, query: "dec" });
  });
});

describe("insertWikilink", () => {
  it("inserts [[name]] replacing the open token", () => {
    const r = insertWikilink("see [[材", { at: 4, query: "材" }, 7, "材料库");
    expect(r.value).toBe("see [[材料库]] ");
  });
  it("preserves text after the caret", () => {
    const tok = activeWikilink("a [[d b", 5)!;
    const out = insertWikilink("a [[d b", tok, 5, "Deck");
    expect(out.value).toBe("a [[Deck]]  b");
  });
  it("returns the caret positioned right after the inserted link", () => {
    const tok = activeWikilink("see [[材", 7)!;
    const out = insertWikilink("see [[材", tok, 7, "材料库");
    expect(out.caret).toBe(out.value.length);
  });
});
