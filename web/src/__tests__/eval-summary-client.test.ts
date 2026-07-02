import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";

afterEach(() => vi.restoreAllMocks());

describe("getRuns", () => {
  it("GETs /runs with spawn_id + limit", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    await api.getRuns(7, 10);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/runs?");
    expect(url).toContain("spawn_id=7");
    expect(url).toContain("limit=10");
  });
});

describe("getRunsSummary", () => {
  it("GETs /runs/summary", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        scored_count: 0, avg_score: null, pass_rate: null,
        dimension_averages: {}, per_spawn: [], recent: [],
      }), { status: 200 }),
    );
    await api.getRunsSummary();
    expect(String(fetchMock.mock.calls[0][0])).toContain("/runs/summary");
  });
});
