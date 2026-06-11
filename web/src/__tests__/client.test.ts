import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { useAuthStore } from "../stores/authStore";

function mockFetch(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  useAuthStore.setState({ token: "" });
});

describe("api client", () => {
  it("GET /spawns returns parsed json", async () => {
    const f = mockFetch([{ id: 1, name: "x" }]);
    vi.stubGlobal("fetch", f);
    const rows = await api.listSpawns();
    expect(rows[0].name).toBe("x");
    expect(f).toHaveBeenCalledWith("/api/v1/spawns", expect.objectContaining({ method: "GET" }));
  });

  it("adds Authorization header when token is set", async () => {
    useAuthStore.setState({ token: "tok123" });
    const f = mockFetch([]);
    vi.stubGlobal("fetch", f);
    await api.listSpawns();
    const headers = (f.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok123");
  });

  it("throws ApiError on non-2xx", async () => {
    const f = mockFetch({ detail: "nope" }, 404);
    vi.stubGlobal("fetch", f);
    await expect(api.getSpawn(99)).rejects.toThrow("nope");
  });

  it("getRegistry GETs /api/v1/registry", async () => {
    const f = mockFetch({ toolsets: [], skills: [] });
    vi.stubGlobal("fetch", f);
    await api.getRegistry();
    expect(f).toHaveBeenCalledWith("/api/v1/registry", expect.objectContaining({ method: "GET" }));
  });

  it("updateEquipment PUTs to /api/v1/spawns/3/equipment with JSON body", async () => {
    const f = mockFetch({ id: 3, name: "x" });
    vi.stubGlobal("fetch", f);
    await api.updateEquipment(3, { toolsets: ["web_search_scraping"], skills: [] });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/v1/spawns/3/equipment");
    expect((init as RequestInit).method).toBe("PUT");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ toolsets: ["web_search_scraping"], skills: [] });
  });
});

describe("api.facts", () => {
  it("lists facts", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch([{ id: 1, content: "metric", source: "auto", sensitive: false }]),
    );
    const facts = await api.listFacts();
    expect(facts).toHaveLength(1);
    expect(facts[0].content).toBe("metric");
  });

  it("adds a fact via POST", async () => {
    const f = mockFetch({ id: 2, content: "x", source: "manual", sensitive: false }, 201);
    vi.stubGlobal("fetch", f);
    await api.addFact({ content: "x", sensitive: false });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ content: "x", sensitive: false });
  });

  it("deletes a fact via DELETE", async () => {
    const f = mockFetch(undefined, 204);
    vi.stubGlobal("fetch", f);
    await api.deleteFact(2);
    const [url, init] = f.mock.calls[0];
    expect(url).toContain("/facts/2");
    expect((init as RequestInit).method).toBe("DELETE");
  });
});
