import { describe, it, expect, vi, beforeEach } from "vitest";
import * as client from "../api/client";

beforeEach(() => {
  global.fetch = vi.fn(async () => ({ ok: true, json: async () => [] })) as never;
});

describe("provider config client", () => {
  it("lists configs via GET /settings/provider-configs", async () => {
    await client.listProviderConfigs();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/settings/provider-configs"),
      expect.anything(),
    );
  });

  it("adds a config via POST /settings/provider-configs", async () => {
    await client.addProviderConfig({
      label: "My OpenAI",
      provider: "openai",
      model: "gpt-4o",
      base_url: "https://api.openai.com/v1",
      api_key: "sk-test",
    });
    const [url, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/settings/provider-configs");
    expect(opts.method).toBe("POST");
  });

  it("updates a config via PUT /settings/provider-configs/:id", async () => {
    await client.updateProviderConfig(3, { label: "Updated" });
    const [url, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/settings/provider-configs/3");
    expect(opts.method).toBe("PUT");
  });

  it("sets primary via PATCH /settings/provider-configs/:id/primary", async () => {
    await client.setPrimaryProviderConfig(7);
    const [url, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/settings/provider-configs/7/primary");
    expect(opts.method).toBe("PATCH");
  });

  it("deletes a config via DELETE /settings/provider-configs/:id", async () => {
    await client.deleteProviderConfig(5);
    const [, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(opts.method).toBe("DELETE");
  });
});
