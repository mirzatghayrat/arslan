/**
 * Filtering what you already have (Capability Library).
 *
 * The Discover tab's search box looks OUTWARD — it searches GitHub for things
 * you do not have. Nothing looked inward, so finding an installed toolset among
 * dozens meant scrolling. These are the matching rules, tested without
 * rendering, because the same rules serve three lists with three different
 * shapes and only the rules should be shared.
 */
import { describe, test, expect } from "vitest";
import {
  filterItems,
  matchedChildren,
  matches,
  normalizeQuery,
} from "../lib/capabilitySearch";

const WEB = {
  // Named differently from the tools it holds — the realistic and the
  // interesting case, since a set whose own key contains the query would match
  // on its own and never exercise the nested path.
  key: "browsing",
  name: "Browsing",
  description: "Read pages.",
  tools: [
    { key: "web_search", name: "web_search", description: "Search the web." },
    { key: "web_extract", name: "web_extract", description: "Fetch a URL." },
  ],
};
const FILES = {
  key: "file_operations",
  name: "File Operations",
  description: "Read & search files.",
  tools: [{ key: "read_file", name: "read_file", description: "Read a file." }],
};

describe("an empty query is not a filter", () => {
  test.each(["", "   ", null, undefined])("%p shows everything", (q) => {
    expect(normalizeQuery(q as string)).toBe("");
    expect(filterItems([WEB, FILES], q as string)).toHaveLength(2);
  });

  test("matches() itself says yes to an empty query", () => {
    // Not redundant with the filterItems cases above: filterItems short-circuits
    // before it ever calls matches, so its contract for an empty query was
    // untested — and McpServers calls matches DIRECTLY. Without this, an
    // implementation that dropped the guard would hide every server until you
    // typed, and the whole suite would still be green. (Found by mutation.)
    expect(matches(WEB, "")).toBe(true);
    expect(matches(WEB, "   ")).toBe(true);
  });

  test("an empty query returns a COPY, not the original array", () => {
    const input = [WEB, FILES];
    const out = filterItems(input, "");
    expect(out).toEqual(input);
    expect(out).not.toBe(input);   // a caller sorting the result must not sort the source
  });
});

describe("what counts as a match", () => {
  test("the name", () => expect(matches(WEB, "browsing")).toBe(true));
  test("the key", () => expect(matches(FILES, "file_operations")).toBe(true));
  test("the description", () => expect(matches(FILES, "read &")).toBe(true));
  test("case does not matter", () => expect(matches(WEB, "BROWSING")).toBe(true));
  test("surrounding whitespace does not matter", () =>
    expect(matches(WEB, "  browsing  ")).toBe(true));
  test("something absent does not match", () =>
    expect(matches(WEB, "kubernetes")).toBe(false));
});

describe("searching for a TOOL finds the set that holds it", () => {
  // The case that justifies the whole nested path: people look for `web_search`,
  // and `web_search` is not a card — it lives inside one.
  test("a toolset surfaces when only its inner tool matches", () => {
    expect(filterItems([WEB, FILES], "web_extract")).toEqual([WEB]);
  });

  test("and it says WHICH tool it matched on", () => {
    expect(matchedChildren(WEB, "web_extract")).toEqual(["web_extract"]);
  });

  test("but not when the set itself already matched", () => {
    // The line explains a card that would otherwise look arbitrary. When the
    // name is right there on the card, repeating it is noise.
    expect(matchedChildren(WEB, "Browsing")).toEqual([]);
  });

  test("a query matching BOTH the set and its tools reports no children", () => {
    // Found while writing these: the parent wins. Worth pinning rather than
    // leaving to chance, because it decides whether a card grows an extra line
    // for a reason the user can already see on it.
    const overlapping = { ...WEB, description: "Read pages with web_search." };
    expect(matches(overlapping, "web_search")).toBe(true);
    expect(matchedChildren(overlapping, "web_search")).toEqual([]);
  });

  test("several matching tools are all reported", () => {
    expect(matchedChildren(WEB, "web_")).toEqual(["web_search", "web_extract"]);
  });

  test("an item with no tools at all is handled", () => {
    const skill = { key: "structured_research", name: "Structured Research", description: "" };
    expect(matchedChildren(skill, "anything")).toEqual([]);
    expect(filterItems([skill], "structured")).toEqual([skill]);
  });
});

describe("a query that matches nothing", () => {
  test("returns an empty list rather than everything", () => {
    // Failing open here would be the worst outcome: the user types a typo and
    // concludes the filter is broken, or worse, that it worked.
    expect(filterItems([WEB, FILES], "zzzz")).toEqual([]);
  });
});
