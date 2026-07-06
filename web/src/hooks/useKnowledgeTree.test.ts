import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  api: {
    listSpawns: vi.fn(), listFacts: vi.fn(), listCollections: vi.fn(),
    getKnowledge: vi.fn(), getCollectionKnowledge: vi.fn(),
  },
}));
import { api } from "../api/client";
import { useKnowledgeTree } from "./useKnowledgeTree";

const m = (k: keyof typeof api) => api[k] as ReturnType<typeof vi.fn>;
afterEach(() => vi.clearAllMocks());

describe("useKnowledgeTree", () => {
  it("assembles a 3-category tree with values summed bottom-up", async () => {
    m("listSpawns").mockResolvedValue([{ id: 1, name: "Research" }]);
    m("listFacts").mockResolvedValue([{ id: 7, content: "语气", source: "auto", sensitive: false }]);
    m("listCollections").mockResolvedValue([{ id: 9, name: "保险资料", chunks: 10, sources: 2, spawn_ids: [] }]);
    m("getKnowledge").mockResolvedValue([{ source: "报告.pdf", chunks: 3 }]);
    m("getCollectionKnowledge").mockResolvedValue([{ source: "条款.pdf", chunks: 6 }, { source: "FAQ", chunks: 4 }]);

    const { result } = renderHook(() => useKnowledgeTree());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const t = result.current.tree;
    expect(t.id).toBe("root");
    const cats = t.children!.map((c) => c.name);
    expect(cats).toEqual(["共享库", "分身深井", "偏好"]);
    const coll = t.children![0].children![0];
    expect(coll.id).toBe("coll:9");
    expect(coll.value).toBe(10);
    expect(coll.children!.map((s) => s.id)).toEqual(["src:coll:9:条款.pdf", "src:coll:9:FAQ"]);
    expect(t.children![1].children![0].id).toBe("spawn:1");
    expect(t.children![2].children![0].id).toBe("pref:7");
    expect(t.value).toBe(10 + 3 + 1);
  });

  it("degrades to root-only when every fetch fails", async () => {
    m("listSpawns").mockRejectedValue(new Error("x"));
    m("listFacts").mockRejectedValue(new Error("x"));
    m("listCollections").mockRejectedValue(new Error("x"));
    const { result } = renderHook(() => useKnowledgeTree());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tree.id).toBe("root");
    expect(result.current.tree.children!.every((c) => (c.children ?? []).length === 0)).toBe(true);
  });
});
