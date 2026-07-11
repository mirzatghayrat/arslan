import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "../api/client";

beforeEach(() => {
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({}),
  })) as never;
});

describe("usage client (S3-M3)", () => {
  it("getConversationUsage hits GET /conversations/:id/usage", async () => {
    await api.getConversationUsage("c9");
    const [url] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/conversations/c9/usage");
  });

  it("getUsageSummary passes the range", async () => {
    await api.getUsageSummary("30d");
    const [url] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/usage/summary?range=30d");
  });

  it("generateTitle sends conversation_id so the titler's tokens are attributable (S2 fold-in)", async () => {
    await api.generateTitle("hello", "reply", "conv-7");
    const [url, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/orchestrator/title");
    expect(JSON.parse(opts.body)).toMatchObject({
      first_message: "hello",
      first_reply: "reply",
      conversation_id: "conv-7",
    });
  });

  it("generateTitle without a conversation id omits the field (optional on the wire)", async () => {
    await api.generateTitle("hello");
    const [, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(opts.body);
    expect(body.first_message).toBe("hello");
    expect("conversation_id" in body ? body.conversation_id : undefined).toBeUndefined();
  });
});
