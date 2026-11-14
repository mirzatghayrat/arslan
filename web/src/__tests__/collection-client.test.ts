import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";

// Moved from knowledge-client.test.ts when the per-spawn knowledge upload went (C7c, v0.1.64).

afterEach(() => vi.restoreAllMocks());

describe("collection client", () => {
  it("ingestCollectionFile posts FormData without a JSON content-type", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ source: "f.txt", chunks_added: 1 }), { status: 200 }),
    );
    const file = new File(["hi"], "f.txt", { type: "text/plain" });
    const out = await api.ingestCollectionFile(7, file);
    expect(out).toEqual({ source: "f.txt", chunks_added: 1 });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    const headers = (init.headers ?? {}) as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
  });
});
