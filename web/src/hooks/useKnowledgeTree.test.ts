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
    // spawn tree is now grouped by domain (fallback "其他" when domain missing)
    const spawnDomainGroup = t.children![1].children![0];
    expect(spawnDomainGroup.kind).toBe("category");
    expect(spawnDomainGroup.children![0].id).toBe("spawn:1");
    // pref tree is now grouped by category (fallback "其他" when category missing)
    const prefCategoryGroup = t.children![2].children![0];
    expect(prefCategoryGroup.kind).toBe("category");
    expect(prefCategoryGroup.children![0].id).toBe("pref:7");
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

  it("groups prefs by category, spawns by domain, sources by fileType", async () => {
    m("listSpawns").mockResolvedValue([{ id: 1, name: "Research", domain: "research.web-research" }]);
    m("listFacts").mockResolvedValue([
      { id: 7, content: "在北京工作", source: "auto", category: "身份背景" },
      { id: 8, content: "喜欢中文", source: "auto", category: null },
    ]);
    m("listCollections").mockResolvedValue([{ id: 9, name: "保险", chunks: 6, sources: 1, spawn_ids: [] }]);
    m("getKnowledge").mockResolvedValue([{ source: "报告.pdf", chunks: 3 }]);
    m("getCollectionKnowledge").mockResolvedValue([{ source: "条款.pdf", chunks: 6 }]);
    const { result } = renderHook(() => useKnowledgeTree());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const t = result.current.tree;
    const pref = t.children!.find((c) => c.id === "cat:pref")!;
    expect(pref.children!.map((g) => g.name).sort()).toEqual(["其他", "身份背景"]); // NULL→其他
    const spawnCat = t.children!.find((c) => c.id === "cat:spawn")!;
    expect(spawnCat.children![0].name).toBe("research");           // domain group
    const coll = t.children!.find((c) => c.id === "cat:collection")!.children![0];
    expect(coll.children![0].fileType).toBe("pdf");                // source fileType
  });

  it("uses label as the pref leaf name and keeps full content", async () => {
    m("listSpawns").mockResolvedValue([]);
    m("listFacts").mockResolvedValue([
      { id: 7, content: "用户希望创建一个专门处理GitHub项目分析的分身", source: "auto", category: "想建的分身", label: "GitHub 分析分身" },
      { id: 8, content: "喜欢中文", source: "auto", category: "沟通偏好", label: null },
    ]);
    m("listCollections").mockResolvedValue([]);
    m("getKnowledge").mockResolvedValue([]);
    m("getCollectionKnowledge").mockResolvedValue([]);
    const { result } = renderHook(() => useKnowledgeTree());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const pref = result.current.tree.children!.find((c) => c.id === "cat:pref")!;
    const leaves = pref.children!.flatMap((g) => g.children!);
    const withLabel = leaves.find((l) => l.id === "pref:7")!;
    expect(withLabel.name).toBe("GitHub 分析分身");                       // label as name
    expect(withLabel.full).toBe("用户希望创建一个专门处理GitHub项目分析的分身"); // full kept
    const noLabel = leaves.find((l) => l.id === "pref:8")!;
    expect(noLabel.name).toBe("喜欢中文");                               // falls back to content
  });
});
