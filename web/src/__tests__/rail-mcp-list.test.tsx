import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import RailMcpList from "../components/RailMcpList";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

describe("RailMcpList", () => {
  it("lists connected/exposed MCP servers", () => {
    render(<RailMcpList servers={[{ id: 7, name: "filesystem-mcp", connected: true, exposed: true }]} />);
    expect(screen.getByText(/filesystem-mcp/)).toBeDefined();
  });
  it("shows an honest empty state when none", () => {
    render(<RailMcpList servers={[]} />);
    expect(screen.getByText("rail.mcp_none")).toBeDefined();
  });
});
