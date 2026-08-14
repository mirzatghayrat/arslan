/**
 * The Authorize button: the user-visible end of the OAuth flow.
 *
 * Only on http servers whose failure was CLASSIFIED as authorization (step 1's
 * classifier feeds this — the two PRs meet here). Click → backend starts the
 * flow → the auth URL goes to the SHELL doorway, never window.open: ruling ③A's
 * provenance rule is that the URL travels backend → response → open_external
 * and nothing else may mint one.
 */
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const servers = vi.fn();
const authorize = vi.fn();
const oauthStatus = vi.fn();
vi.mock("../api/mcp", () => ({
  listMcpServers: (...a: unknown[]) => servers(...a),
  addMcpServer: vi.fn(),
  connectMcpServer: vi.fn(async () => ({})),
  reconnectMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  listMcpTools: vi.fn(async () => []),
  wireMcpTool: vi.fn(),
  authorizeMcpOauth: (...a: unknown[]) => authorize(...a),
  getMcpOauthStatus: (...a: unknown[]) => oauthStatus(...a),
}));
const openExternal = vi.fn();
vi.mock("../lib/shell", () => ({
  openExternal: (...a: unknown[]) => openExternal(...a),
  shellAvailable: () => true,
}));

import McpServers from "../components/McpServers";

const httpServer = {
  id: 3, label: "Remote", transport: "http", url: "http://mcp.x/mcp",
  command: "", args: [], env: {}, env_status: "unset", status: "error",
  last_error: "authorization failed (HTTP 401): no credentials are configured for this server — it requires authentication",
  tools: [],
};

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Authorize", () => {
  it("appears on an http server whose error is an authorization failure", async () => {
    servers.mockResolvedValue([httpServer]);
    render(<McpServers />);
    await waitFor(() => expect(screen.getByText("Remote")).toBeTruthy());
    expect(screen.getByTestId("mcp-authorize-3")).toBeTruthy();
  });

  it("does not appear on a stdio server, whatever its error says", async () => {
    servers.mockResolvedValue([{ ...httpServer, transport: "stdio", command: "npx" }]);
    render(<McpServers />);
    await waitFor(() => expect(screen.getByText("Remote")).toBeTruthy());
    expect(screen.queryByTestId("mcp-authorize-3")).toBeNull();
  });

  it("does not appear when the failure is not about authorization", async () => {
    // An unreachable host needs a network fix, not a browser round-trip; the
    // button would send the user through a flow that cannot help.
    servers.mockResolvedValue([{ ...httpServer, last_error: "connect timeout" }]);
    render(<McpServers />);
    await waitFor(() => expect(screen.getByText("Remote")).toBeTruthy());
    expect(screen.queryByTestId("mcp-authorize-3")).toBeNull();
  });

  it("opens the backend's URL through the shell doorway and polls to done", async () => {
    servers.mockResolvedValue([httpServer]);
    authorize.mockResolvedValue({ auth_url: "https://auth.example/a" });
    oauthStatus.mockResolvedValue({ state: "done", error: "" });
    render(<McpServers />);
    await waitFor(() => expect(screen.getByTestId("mcp-authorize-3")).toBeTruthy());
    fireEvent.click(screen.getByTestId("mcp-authorize-3"));
    await waitFor(() => expect(openExternal).toHaveBeenCalledWith("https://auth.example/a"));
    await waitFor(() => expect(oauthStatus).toHaveBeenCalled());
  });

  it("surfaces a refused flow instead of spinning forever", async () => {
    servers.mockResolvedValue([httpServer]);
    authorize.mockResolvedValue({ auth_url: "https://auth.example/a" });
    oauthStatus.mockResolvedValue({ state: "error", error: "authorization refused: access_denied" });
    render(<McpServers />);
    await waitFor(() => expect(screen.getByTestId("mcp-authorize-3")).toBeTruthy());
    fireEvent.click(screen.getByTestId("mcp-authorize-3"));
    await waitFor(() => expect(screen.getByText(/access_denied/)).toBeTruthy());
  });
});
