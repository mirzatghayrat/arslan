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
});
