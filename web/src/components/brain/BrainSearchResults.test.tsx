/**
 * The search results panel.
 *
 * The assertion that matters most is a NEGATIVE one: no relevance score may be
 * rendered. rerank is lexical overlap, so a number here would be a claim the
 * system cannot make — and "let's show a percentage, it looks more useful" is
 * exactly the change that passes review on its way in.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, o?: Record<string, unknown>) =>
      o && "count" in o ? `${k}:${o.count}` : k,
  }),
}));

import BrainSearchResults from "./BrainSearchResults";

const HITS = [
  { kind: "fact", ref: "12", title: "fact:12", snippet: "crypto_salt 与 SECRET_KEY 必须配对" },
  { kind: "note", ref: "3", title: "note:3", snippet: "开源迁移后的唯一开发树" },
];

const base = {
  query: "salt", ranking: "lexical" as const, truncated: false,
  results: HITS, onHover: vi.fn(), onOpen: vi.fn(),
};

it("names the pipeline that ran, in words", () => {
  const { rerender } = render(<BrainSearchResults {...base} />);
  expect(screen.getByText("brain.search_ranking_lexical")).toBeTruthy();
  rerender(<BrainSearchResults {...base} ranking="hybrid" />);
  expect(screen.getByText("brain.search_ranking_hybrid")).toBeTruthy();
});

it("renders no relevance score anywhere", () => {
  render(<BrainSearchResults {...base} />);
  const text = screen.getByTestId("brain-search-results").textContent ?? "";
  // Any bare decimal or percentage would be read as semantic confidence.
  expect(text).not.toMatch(/\d+(\.\d+)?\s*%/);
  expect(text).not.toMatch(/0\.\d\d/);
});

it("shows the matched text so a hit can be judged without opening it", () => {
  render(<BrainSearchResults {...base} />);
  expect(screen.getByText(/crypto_salt/)).toBeTruthy();
});

it("says when the list was capped", () => {
  const { rerender } = render(<BrainSearchResults {...base} />);
  expect(screen.queryByText("brain.search_truncated")).toBeNull();
  rerender(<BrainSearchResults {...base} truncated />);
  expect(screen.getByText("brain.search_truncated")).toBeTruthy();
});

it("distinguishes no matches from no search", () => {
  const { rerender } = render(<BrainSearchResults {...base} results={[]} />);
  expect(screen.getByText("brain.search_no_hits")).toBeTruthy();
  // An empty query renders nothing at all — "you have not searched" and "your
  // memory has nothing" are different statements.
  rerender(<BrainSearchResults {...base} query="" results={[]} />);
  expect(screen.queryByTestId("brain-search-results")).toBeNull();
});

it("drives the coordinated highlight on hover and opens on click", () => {
  const onHover = vi.fn();
  const onOpen = vi.fn();
  render(<BrainSearchResults {...base} onHover={onHover} onOpen={onOpen} />);
  const row = screen.getAllByTestId("brain-search-hit")[0];

  fireEvent.mouseEnter(row);
  expect(onHover).toHaveBeenCalledWith("fact", "12");
  fireEvent.mouseLeave(row);
  expect(onHover).toHaveBeenLastCalledWith("fact", null);

  fireEvent.click(row);
  expect(onOpen).toHaveBeenCalledWith("fact", "12");
});

it("marks the focused row so the highlight is visible in all three views", () => {
  render(<BrainSearchResults {...base} focusedRef="3" />);
  const rows = screen.getAllByTestId("brain-search-hit");
  expect(rows[1].className).toMatch(/is-focused/);
  expect(rows[0].className).not.toMatch(/is-focused/);
});
