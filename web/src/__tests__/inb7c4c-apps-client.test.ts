/** INB7-c4c: the 「应用」 chip's query, as the real client sends it (the page's tests stub the client). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";

afterEach(() => vi.restoreAllMocks());

describe("listRuns with the apps chip", () => {
  it("asks GET /runs for used=apps, and nothing of it otherwise", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("[]", { status: 200 }));
    await api.listRuns({ used: "apps" });
    await api.listRuns({});
    expect(new URL(String(fetchMock.mock.calls[0][0]), "http://x").searchParams.get("used")).toBe("apps");
    expect(new URL(String(fetchMock.mock.calls[1][0]), "http://x").searchParams.has("used")).toBe(false);
  });
});

describe("the axis's 「应用」 chip", () => {
  it("keeps a run that used Mac apps and dims one that did not (⓪Plan's review of PR 636, 1)", async () => {
    const { chipHas } = await import("../components/activity/RunsLane");
    const run = (used_apps: boolean) => ({ id: 1, spawn_id: null, spawn_name: "Arslan", status: "recorded", overall_score: null,
      overall_badge: null, total_ms: 1, user_message: "x", created_at: "2026-11-01T09:00:00", origin: "chat" as const, model: "m", tokens: 1,
      used_apps });
    expect(chipHas("apps", run(true))).toBe(true);
    expect(chipHas("apps", run(false))).toBe(false);
    expect(chipHas("phone", run(true))).toBe(false);
  });
});
