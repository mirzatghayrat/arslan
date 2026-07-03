import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useKnowledgeGraph } from "./useKnowledgeGraph";

vi.mock("../api/client", () => ({
  api: {
    listSpawns: vi.fn(),
    listFacts: vi.fn(),
    getKnowledge: vi.fn(),
  },
}));

import { api } from "../api/client";

const listSpawns = api.listSpawns as ReturnType<typeof vi.fn>;
const listFacts = api.listFacts as ReturnType<typeof vi.fn>;
const getKnowledge = api.getKnowledge as ReturnType<typeof vi.fn>;

afterEach(() => vi.clearAllMocks());

describe("useKnowledgeGraph", () => {
  it("assembles nodes+edges with cross-spawn source dedup", async () => {
    listSpawns.mockResolvedValue([
      { id: 1, name: "小红书" },
      { id: 2, name: "金融" },
    ]);
    getKnowledge.mockImplementation((id: number) =>
      id === 1
        ? Promise.resolve([{ source: "a.pdf", chunks: 3 }])
        : Promise.resolve([
            { source: "a.pdf", chunks: 2 },
            { source: "b.md", chunks: 1 },
          ]),
    );
    listFacts.mockResolvedValue([{ id: 9, content: "偏口语" }]);

    const { result } = renderHook(() => useKnowledgeGraph());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const { nodes, edges } = result.current.graph;

    // hub
    const hubs = nodes.filter((n) => n.cat === "hub");
    expect(hubs).toHaveLength(1);
    expect(hubs[0].id).toBe("hub");
    expect(hubs[0].label).toBe("YOU");

    // 2 spawn nodes
    const spawnNodes = nodes.filter((n) => n.cat === "spawn");
    expect(spawnNodes).toHaveLength(2);
    expect(spawnNodes.map((n) => n.id).sort()).toEqual(["spawn:1", "spawn:2"]);

    // sources deduped: a.pdf once + b.md => 2 source nodes
    const sourceNodes = nodes.filter((n) => n.cat === "source");
    expect(sourceNodes).toHaveLength(2);
    expect(sourceNodes.map((n) => n.id).sort()).toEqual(["src:a.pdf", "src:b.md"]);

    // 1 pref node
    const prefNodes = nodes.filter((n) => n.cat === "pref");
    expect(prefNodes).toHaveLength(1);
    expect(prefNodes[0].id).toBe("pref:9");
    expect(prefNodes[0].label).toBe("偏口语");

    // edges: hub->spawn (x2)
    expect(edges).toContainEqual({ a: "hub", b: "spawn:1" });
    expect(edges).toContainEqual({ a: "hub", b: "spawn:2" });
    // both spawns -> a.pdf (dedup node, two edges)
    expect(edges).toContainEqual({ a: "spawn:1", b: "src:a.pdf" });
    expect(edges).toContainEqual({ a: "spawn:2", b: "src:a.pdf" });
    // spawn 2 -> b.md
    expect(edges).toContainEqual({ a: "spawn:2", b: "src:b.md" });
    // hub -> pref
    expect(edges).toContainEqual({ a: "hub", b: "pref:9" });

    expect(result.current.error).toBeNull();
  });

  it("returns hub-only graph when everything is empty", async () => {
    listSpawns.mockResolvedValue([]);
    listFacts.mockResolvedValue([]);
    getKnowledge.mockResolvedValue([]);

    const { result } = renderHook(() => useKnowledgeGraph());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.graph.nodes).toEqual([
      { id: "hub", cat: "hub", label: "YOU" },
    ]);
    expect(result.current.graph.edges).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it("sets error and hub-only graph when listSpawns rejects", async () => {
    listSpawns.mockRejectedValue(new Error("boom"));
    listFacts.mockResolvedValue([]);
    getKnowledge.mockResolvedValue([]);

    const { result } = renderHook(() => useKnowledgeGraph());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("boom");
    expect(result.current.graph.nodes).toEqual([
      { id: "hub", cat: "hub", label: "YOU" },
    ]);
    expect(result.current.graph.edges).toEqual([]);
  });
});
