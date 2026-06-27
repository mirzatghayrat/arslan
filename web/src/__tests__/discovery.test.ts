import { afterEach, describe, expect, it, vi } from "vitest";
import { evaluateRepo } from "../api/discovery";

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
});
