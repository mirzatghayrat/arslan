import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import RailMcpList from "../components/RailMcpList";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

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
});
