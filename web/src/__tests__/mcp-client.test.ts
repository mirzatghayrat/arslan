import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addMcpServer,
  connectMcpServer,
  deleteMcpServer,
  exposeMcpServer,
  listMcpServers,
  listMcpTools,
  reconnectMcpServer,
  setMcpToolHost,
  wireMcpTool,
} from "../api/mcp";

afterEach(() => vi.restoreAllMocks());

function mockFetch(body: unknown = {}) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
}

describe("mcp client", () => {
  it("listMcpServers GETs /mcp/servers", async () => {
    const f = mockFetch([]);
    await listMcpServers();
    expect(f.mock.calls[0][0]).toContain("/mcp/servers");
    expect((f.mock.calls[0][1] as RequestInit).method ?? "GET").toBe("GET");
  });

  it("addMcpServer POSTs /mcp/servers with the body", async () => {
    const f = mockFetch({ id: 1 });
    const body = { label: "fs", command: "npx", args: ["-y", "x"], env: { TOKEN: "s" } };
    await addMcpServer(body);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/mcp/servers");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(body);
  });

  it("connectMcpServer POSTs /mcp/servers/:id/connect", async () => {
    const f = mockFetch([]);
    await connectMcpServer(5);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/mcp/servers/5/connect");
    expect(init.method).toBe("POST");
  });

  it("listMcpTools GETs /mcp/servers/:id/tools", async () => {
    const f = mockFetch([]);
    await listMcpTools(9);
    expect(f.mock.calls[0][0]).toContain("/mcp/servers/9/tools");
  });

  it("exposeMcpServer PATCHes /mcp/servers/:id/expose with { exposed }", async () => {
    const f = mockFetch({ ok: true });
    await exposeMcpServer(3, true);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/mcp/servers/3/expose");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ exposed: true });
  });

  it("wireMcpTool PATCHes the encoded key path with { tier, wired }", async () => {
    const f = mockFetch({ ok: true });
    await wireMcpTool("mcp_2__read_file", "safe", true);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/mcp/tools/mcp_2__read_file/wire");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ tier: "safe", wired: true });
  });

  it("wireMcpTool encodeURIComponent-encodes special chars in the key", async () => {
    const f = mockFetch({ ok: true });
    await wireMcpTool("mcp_2__a/b", "safe", false);
    expect(f.mock.calls[0][0]).toContain("/mcp/tools/mcp_2__a%2Fb/wire");
  });

  it("deleteMcpServer DELETEs /mcp/servers/:id", async () => {
    const f = mockFetch({ ok: true });
    await deleteMcpServer(7);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/mcp/servers/7");
    expect(init.method).toBe("DELETE");
  });

  it("addMcpServer POSTs http transport + url fields", async () => {
    const f = mockFetch({ id: 2 });
    const body = {
      label: "remote",
      args: [],
      env: { Authorization: "Bearer s" },
      transport: "http",
      url: "https://x/mcp",
    };
    await addMcpServer(body);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/mcp/servers");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(body);
  });

  it("setMcpToolHost PATCHes /mcp/tools/:key/host with { enabled }", async () => {
    const f = mockFetch({ ok: true });
    await setMcpToolHost("mcp_1__t", true);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/mcp/tools/mcp_1__t/host");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ enabled: true });
  });

  it("reconnectMcpServer POSTs /mcp/servers/:id/reconnect", async () => {
    const f = mockFetch({ ok: true });
    await reconnectMcpServer(3);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/mcp/servers/3/reconnect");
    expect(init.method).toBe("POST");
  });
});
