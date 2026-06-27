import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createSkill,
  deleteCandidate,
  evaluateRepo,
  generateSkill,
  refreshCandidate,
  saveCandidate,
  searchRepos,
  type EvalResult,
} from "../api/discovery";

afterEach(() => vi.restoreAllMocks());

function mockFetch(body: unknown = {}) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
}

describe("discovery client", () => {
  it("evaluateRepo POSTs /discovery/evaluate with { ref }", async () => {
    const f = mockFetch({
      repo: {
        full_name: "o/r",
        html_url: "https://github.com/o/r",
        stars: 1500,
        forks: 9,
        license: "MIT",
        pushed_days: 20,
        description: "an mcp server",
        topics: ["mcp"],
      },
      trust: { tier: "high", license_note: "MIT: commercial-safe" },
      suggestion: {
        is_mcp: true,
        transport: "stdio",
        command: "npx",
        args: ["-y", "@scope/x"],
        url: null,
        reason: "npx",
      },
    });

    const result = await evaluateRepo("o/r");

    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discovery/evaluate");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ ref: "o/r" });

    // parses the result
    expect(result.repo.stars).toBe(1500);
    expect(result.trust.tier).toBe("high");
    expect(result.suggestion.is_mcp).toBe(true);
    expect(result.suggestion.command).toBe("npx");
  });

  it("searchRepos GETs /discovery/search?q=mcp", async () => {
    const f = mockFetch([]);
    await searchRepos("mcp");
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discovery/search?q=mcp");
    expect(init.method ?? "GET").toBe("GET");
  });

  it("saveCandidate POSTs /discovery/catalog with { snapshot }", async () => {
    const f = mockFetch({});
    const snap = { repo: { full_name: "o/r" } } as unknown as EvalResult;
    await saveCandidate(snap);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discovery/catalog");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ snapshot: snap });
  });

  it("refreshCandidate POSTs /discovery/catalog/3/refresh", async () => {
    const f = mockFetch({});
    await refreshCandidate(3);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discovery/catalog/3/refresh");
    expect(init.method).toBe("POST");
  });

  it("deleteCandidate DELETEs /discovery/catalog/3", async () => {
    const f = mockFetch({});
    await deleteCandidate(3);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discovery/catalog/3");
    expect(init.method).toBe("DELETE");
  });

  it("generateSkill POSTs /discovery/skill/generate with { ref }", async () => {
    const f = mockFetch({
      repo: { full_name: "o/r", html_url: "https://github.com/o/r" },
      skill: { name: "T", category: "research", description: "d", body: "## Trigger\nx\n## 决策规则\ny" },
    });

    const result = await generateSkill("o/r");

    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discovery/skill/generate");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ ref: "o/r" });
    expect(result.skill?.name).toBe("T");
  });

  it("createSkill POSTs /discovery/skill with the payload", async () => {
    const f = mockFetch({
      key: "gh-o-r",
      name: "My Tech",
      category: "research",
      description: "d",
      tier: "safe",
      status: "registered",
    });
    const payload = {
      full_name: "o/r",
      name: "My Tech",
      category: "research",
      description: "d",
      body: "## Trigger\nx\n## 决策规则\ny",
    };

    const result = await createSkill(payload);

    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/discovery/skill");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(payload);
    expect(result.key).toBe("gh-o-r");
    expect(result.tier).toBe("safe");
  });
});
