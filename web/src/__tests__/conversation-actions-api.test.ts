import { describe, it, expect, vi, beforeEach } from "vitest";
import { deleteConversation } from "../api/client";

beforeEach(() => {
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ ok: true, deleted: { runs: 3 } }),
  })) as never;
});

describe("conversation actions client", () => {
  it("deletes a conversation via DELETE /conversations/:id", async () => {
    const result = await deleteConversation("c1");
    const [url, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/conversations/c1");
    expect(opts.method).toBe("DELETE");
    expect(result).toEqual({ ok: true, deleted: { runs: 3 } });
  });
});
