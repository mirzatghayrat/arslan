import { describe, it, expect, vi, beforeEach } from "vitest";
import { distillConversation, deleteConversation } from "../api/client";

beforeEach(() => {
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ ok: true, distilled_spawns: 2, deleted: { runs: 3 } }),
  })) as never;
});

describe("conversation actions client", () => {
  it("distills a conversation via POST /conversations/:id/distill", async () => {
    const result = await distillConversation("c1");
    const [url, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/conversations/c1/distill");
    expect(opts.method).toBe("POST");
    expect(result).toEqual({ ok: true, distilled_spawns: 2, deleted: { runs: 3 } });
  });

  it("deletes a conversation via DELETE /conversations/:id", async () => {
    const result = await deleteConversation("c1");
    const [url, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/conversations/c1");
    expect(url).not.toContain("/distill");
    expect(opts.method).toBe("DELETE");
    expect(result).toEqual({ ok: true, distilled_spawns: 2, deleted: { runs: 3 } });
  });
});
