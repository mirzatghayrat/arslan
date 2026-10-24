import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";

afterEach(() => vi.restoreAllMocks());

describe("knowledge client", () => {
  it("getKnowledge GETs the spawn knowledge list", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ source: "doc", chunks: 3 }]), { status: 200 }),
    );
    const out = await api.getKnowledge(7);
    expect(out).toEqual([{ source: "doc", chunks: 3 }]);
    expect(fetchMock.mock.calls[0][0]).toContain("/spawns/7/knowledge");
  });

  it("ingestKnowledgeFile posts FormData without a JSON content-type", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ source: "f.txt", chunks_added: 1 }), { status: 200 }),
    );
    const file = new File(["hi"], "f.txt", { type: "text/plain" });
    const out = await api.ingestKnowledgeFile(7, file);
    expect(out).toEqual({ source: "f.txt", chunks_added: 1 });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    const headers = (init.headers ?? {}) as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
  });
});
