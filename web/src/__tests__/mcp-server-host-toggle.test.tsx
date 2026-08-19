/**
 * Server-level equipment (user ruling 2026-08-18): connect = usable by Arslan.
 *
 * The server card carries ONE revocable "Allow Arslan" switch (backed by
 * mcp_servers.host_allowed) and the per-tool rows keep only the SPAWN
 * vocabulary (tier + wire) — the old per-tool "allow Arslan" checkbox is gone.
 * The expose checkbox stops lying: it renders the backend's real state
 * instead of a hardcoded false.
 */
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const servers = vi.fn();
const setHost = vi.fn(async (..._a: unknown[]) => ({ ok: true }));
const tools = vi.fn(async (..._a: unknown[]) => [] as unknown[]);
const connect = vi.fn(async (..._a: unknown[]) => [] as unknown[]);
vi.mock("../api/mcp", () => ({
  listMcpServers: (...a: unknown[]) => servers(...a),
  addMcpServer: vi.fn(),
  // connect's RESPONSE is the discovered tool list — the component renders it directly
  connectMcpServer: (...a: unknown[]) => connect(...a),
  reconnectMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  exposeMcpServer: vi.fn(),
  listMcpTools: (...a: unknown[]) => tools(...a),
  wireMcpTool: vi.fn(),
  setMcpServerHost: (...a: unknown[]) => setHost(...a),
  authorizeMcpOauth: vi.fn(),
  getMcpOauthStatus: vi.fn(),
}));
vi.mock("../lib/shell", () => ({
  openExternal: vi.fn(),
  shellAvailable: () => true,
}));

import McpServers from "../components/McpServers";

const base = {
  id: 3, label: "Playwright", transport: "stdio", url: null,
  command: "npx", args: ["-y", "@playwright/mcp@latest"], env: {}, env_status: "unset",
  status: "connected", last_error: null, host_allowed: true, exposed: true,
};

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("server-level Allow Arslan", () => {
  it("renders one switch per server, checked from host_allowed", async () => {
    servers.mockResolvedValue([base]);
    render(<McpServers />);
    await waitFor(() => expect(screen.getByText("Playwright")).toBeTruthy());
    const toggle = screen.getByTestId("mcp-host-3") as HTMLInputElement;
    expect(toggle.checked).toBe(true);
  });

  it("click calls the server-level endpoint with the flipped value", async () => {
    servers.mockResolvedValue([base]);
    render(<McpServers />);
    await waitFor(() => expect(screen.getByTestId("mcp-host-3")).toBeTruthy());
    fireEvent.click(screen.getByTestId("mcp-host-3"));
    await waitFor(() => expect(setHost).toHaveBeenCalledWith(3, false));
  });

  it("renders unchecked when host_allowed is off", async () => {
    servers.mockResolvedValue([{ ...base, host_allowed: false }]);
    render(<McpServers />);
    await waitFor(() => expect(screen.getByTestId("mcp-host-3")).toBeTruthy());
    expect((screen.getByTestId("mcp-host-3") as HTMLInputElement).checked).toBe(false);
  });

  it("tool rows keep the spawn vocabulary and lose the per-tool host checkbox", async () => {
    servers.mockResolvedValue([base]);
    connect.mockResolvedValue([{
      key: "mcp_3__browser_click", name: "browser_click", description: "d",
      tier: "orchestrator", status: "registered", suggested_tier: "orchestrator",
      host_enabled: false,
    }]);
    render(<McpServers />);
    await waitFor(() => expect(screen.getByText("Playwright")).toBeTruthy());
    fireEvent.click(screen.getByText("Connect"));
    await waitFor(() => expect(screen.getByText("browser_click")).toBeTruthy());
    expect(screen.getByLabelText("tier for browser_click")).toBeTruthy();   // spawn vocab stays
    expect(screen.queryByText("allow Arslan")).toBeNull();                  // per-tool switch gone
  });

  it("the expose checkbox reflects the backend's real state, not a hardcoded false", async () => {
    servers.mockResolvedValue([{ ...base, exposed: true }]);
    render(<McpServers />);
    await waitFor(() => expect(screen.getByText("Playwright")).toBeTruthy());
    const expose = screen.getByTestId("mcp-expose-3") as HTMLInputElement;
    expect(expose.checked).toBe(true);
  });
});
