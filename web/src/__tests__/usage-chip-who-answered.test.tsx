/**
 * The chip says which model answered — and says so for BOTH of them when two ran.
 *
 * The data existed all along (usage_sink.detail()'s per-model buckets) and was thrown
 * away at the frame boundary, so the surface a person actually watches never said.
 * Spec ② can now route a task elsewhere on purpose, which makes "no silently swapping
 * models and spending the user's money" only as real as this line.
 */
import { render, screen, cleanup } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import UsageChip from "../components/UsageChip";
import type { StreamUsage } from "../api/client.types";

const usage = (over: Partial<StreamUsage> = {}): StreamUsage => ({
  tokens_in: 100, tokens_out: 40, tokens_total: 140,
  estimated: false, usd: 0.002, models: [], ...over,
});

describe("<UsageChip> who answered", () => {
  it("names the model that ran", () => {
    render(<UsageChip usage={usage({ models: [{ model: "deepseek-chat", provider: "deepseek" }] })} />);
    expect(screen.getByTestId("usage-models").textContent).toContain("deepseek-chat");
  });

  it("names BOTH when two models ran", () => {
    // THE case. Showing only the busiest would hide the swap this exists to reveal.
    render(<UsageChip usage={usage({ models: [
      { model: "deepseek-chat", provider: "deepseek" },
      { model: "gpt-4o-mini", provider: "openai" },
    ] })} />);
    const text = screen.getByTestId("usage-models").textContent ?? "";
    expect(text).toContain("deepseek-chat");
    expect(text).toContain("gpt-4o-mini");
  });

  it("says nothing when no model ran", () => {
    render(<UsageChip usage={usage({ models: [] })} />);
    expect(screen.queryByTestId("usage-models")).toBeNull();
  });

  it("survives a frame recorded before this field existed", () => {
    // Old rows have no `models` at all. The chip must render its numbers, not crash.
    cleanup();
    const old = { ...usage() } as Partial<StreamUsage>;
    delete old.models;
    render(<UsageChip usage={old as StreamUsage} />);
    expect(screen.getByTestId("usage-chip").textContent).toContain("tok");
    expect(screen.queryByTestId("usage-models")).toBeNull();
  });
});
