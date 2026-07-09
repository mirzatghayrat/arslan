import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import RailMcpList from "../components/RailMcpList";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
const checkMcpHealth = vi.fn();
vi.mock("../api/client", () => ({ api: { checkMcpHealth: (id: number) => checkMcpHealth(id) } }));

describe("RailMcpList", () => {
  it("lists registered MCP servers by their real label (status drives the dot)", () => {
    // Real /mcp/servers shape: { id, label, status }.
    render(<RailMcpList servers={[{ id: 7, label: "filesystem-mcp", status: "connected" }]} />);
    expect(screen.getByText(/filesystem-mcp/)).toBeDefined();
  });
  it("shows an honest empty state when none", () => {
    render(<RailMcpList servers={[]} />);
    expect(screen.getByText("rail.mcp_none")).toBeDefined();
  });
  it("shows a health badge: failing → danger dot with last_error tooltip, unchecked → muted", () => {
    render(
      <RailMcpList
        servers={[
          { id: 1, label: "fetch", status: "connected", health_status: "failing", last_error: "boom" },
          { id: 2, label: "fs", status: "connected" },
        ]}
      />,
    );
    const failing = screen.getByTestId("mcp-health-1");
    expect(failing.className).toContain("bg-danger");
    expect(failing.getAttribute("title")).toBe("boom");     // honest upstream error surfaced
    const unknown = screen.getByTestId("mcp-health-2");
    expect(unknown.className).toContain("bg-subtle-foreground");
    expect(unknown.getAttribute("title")).toBe("rail.mcp_health_unknown");
  });
  it("体检 button probes the server and refreshes the badge in place", async () => {
    checkMcpHealth.mockResolvedValueOnce({ health_status: "ok", last_error: null });
    render(
      <RailMcpList
        servers={[{ id: 3, label: "fetch", status: "connected", health_status: "failing", last_error: "old" }]}
      />,
    );
    expect(screen.getByTestId("mcp-health-3").className).toContain("bg-danger");
    fireEvent.click(screen.getByText("rail.mcp_health_check"));
    await waitFor(() => {
      expect(checkMcpHealth).toHaveBeenCalledWith(3);
      expect(screen.getByTestId("mcp-health-3").className).toContain("bg-success");
    });
  });
});
