import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";

afterEach(() => vi.restoreAllMocks());

describe("knowledge/evolution client", () => {
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

  it("runEvolve POSTs the evolve endpoint and returns the enqueued attempt id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ attempt_id: 42 }), { status: 202 }),
    );
    const out = await api.runEvolve(7);
    expect(out.attempt_id).toBe(42);
    expect(fetchMock.mock.calls[0][0]).toContain("/spawns/7/evolve");
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("getEvolutionProposals GETs the inbox with an optional status filter", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    await api.getEvolutionProposals("open");
    expect(fetchMock.mock.calls[0][0]).toContain("/evolution/proposals?status=open");
  });

  it("getProposalDetail GETs one proposal's full evidence", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: 3 }), { status: 200 }),
    );
    await api.getProposalDetail(3);
    expect(fetchMock.mock.calls[0][0]).toContain("/evolution/proposals/3");
  });

  it("rollbackProposal POSTs the rollback endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true, generation_level: 1 }), { status: 200 }),
    );
    const out = await api.rollbackProposal(3);
    expect(out.ok).toBe(true);
    expect(fetchMock.mock.calls[0][0]).toContain("/evolution/proposals/3/rollback");
  });
});
