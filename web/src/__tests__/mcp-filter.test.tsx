/**
 * The same filter on the MCPS tab.
 *
 * Worth its own file because this list takes a different path: McpServers calls
 * `matches` directly rather than going through `filterItems`, so the "empty
 * query shows everything" contract is exercised here and nowhere else in the UI.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach } from "vitest";
import McpServers from "../components/McpServers";
import * as mcpApi from "../api/mcp";
import "../i18n";

vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn(),
  addMcpServer: vi.fn(),
  connectMcpServer: vi.fn(),
  exposeMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  listMcpTools: vi.fn(async () => []),
  setMcpToolTier: vi.fn(),
  setMcpToolHost: vi.fn(),
  setMcpServerHost: vi.fn(),
  getMcpHealth: vi.fn(async () => null),
}));

const SERVERS = [
  { id: 1, label: "notion", command: "npx", args: ["-y", "@notionhq/mcp"], env: {},
    status: "connected", transport: "stdio", host_allowed: true, exposed: false },
  { id: 2, label: "playwright", command: "npx", args: ["-y", "@playwright/mcp"], env: {},
    status: "connected", transport: "stdio", host_allowed: true, exposed: false },
];

describe("filtering the MCP server list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(mcpApi.listMcpServers).mockResolvedValue(SERVERS as never);
  });

  test("every server is listed before you type", async () => {
    // The contract a mutation caught me missing: this list asks `matches`
    // directly, so an empty query has to mean "show everything" HERE too.
    render(<McpServers />);
    expect(await screen.findByText("notion")).toBeInTheDocument();
    expect(screen.getByText("playwright")).toBeInTheDocument();
  });

  test("typing narrows to one", async () => {
    render(<McpServers />);
    await screen.findByText("notion");
    fireEvent.change(screen.getByTestId("mcp-filter"), { target: { value: "play" } });
    await waitFor(() => expect(screen.queryByText("notion")).toBeNull());
    expect(screen.getByText("playwright")).toBeInTheDocument();
  });

  test("you can find a server by how it is reached, not just its label", async () => {
    // "the one I pointed at playwright" is how people remember these; the
    // package name is often more memorable than the label they typed once.
    render(<McpServers />);
    await screen.findByText("notion");
    fireEvent.change(screen.getByTestId("mcp-filter"), { target: { value: "@playwright" } });
    await waitFor(() => expect(screen.getByText("playwright")).toBeInTheDocument());
    expect(screen.queryByText("notion")).toBeNull();
  });

  test("hiding everything reads as a filter, not as an empty library", async () => {
    render(<McpServers />);
    await screen.findByText("notion");
    fireEvent.change(screen.getByTestId("mcp-filter"), { target: { value: "zzzz" } });
    await waitFor(() => expect(screen.getByTestId("mcp-filter-empty")).toBeInTheDocument());
    expect(screen.getByTestId("mcp-filter-count")).toHaveTextContent("0");
  });
});
