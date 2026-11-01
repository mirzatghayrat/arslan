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
