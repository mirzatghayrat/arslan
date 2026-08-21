/**
 * The tool-transport notice on the Capability Library (ruling ①).
 *
 * The failure it describes has no symptom. On a provider Arslan does not send
 * tool definitions to, you can equip a toolset, connect an MCP server, tick
 * "Allow Arslan (all tools)" — and every one of those surfaces reads as
 * installed while the model is never told any of it exists. Settings already
 * warns, but the person ticking a box here chose their provider months ago and
 * is not going to open Settings first.
 *
 * The insertion is ABOVE the tab bar on purpose: one place, all six tabs,
 * including MCPS — which is where the most confident false claim in the app
 * lives.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach } from "vitest";
import Capabilities from "../components/Capabilities";
import "../i18n";

vi.mock("../api/catalog", () => ({ getMcpCatalog: vi.fn(async () => []) }));
vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn(async () => []),
  addMcpServer: vi.fn(),
  connectMcpServer: vi.fn(),
  exposeMcpServer: vi.fn(),
}));

describe("the Capability Library says when equipping will have no effect", () => {
  beforeEach(() => vi.clearAllMocks());

  test("a provider that cannot carry tools is called out", () => {
    render(<Capabilities provider="gemini" />);
    const notice = screen.getByTestId("tool-transport-warning");
    expect(notice).toHaveAttribute("data-state", "unsupported");
    // MCP servers are named in the copy, because the MCPS tab is where someone
    // is most likely to believe a checkbox did something.
    expect(notice).toHaveTextContent(/MCP/i);
  });

  test("the notice names the provider it is about", () => {
    // On Settings, "this provider" points at the select directly above it. Here
    // there is no antecedent on the page at all, and an unattributed warning
    // gets read as being about something else.
    render(<Capabilities provider="gemini" />);
    expect(screen.getByTestId("tool-transport-provider")).toHaveTextContent("gemini");
  });

  test("a provider that carries tools gets no notice", () => {
    render(<Capabilities provider="openai" />);
    expect(screen.queryByTestId("tool-transport-warning")).toBeNull();
  });

  test("an unmeasured provider gets the quieter notice, not the loud one", () => {
    render(<Capabilities provider="something-nobody-tested" />);
    expect(screen.getByTestId("tool-transport-warning"))
      .toHaveAttribute("data-state", "unverified");
  });

  test("no configured provider means no notice at all", () => {
    // Someone who has not set up a provider is in the first-run flow. Telling
    // them their unset provider is unmeasured is noise wearing a safety notice's
    // clothes.
    render(<Capabilities />);
    expect(screen.queryByTestId("tool-transport-warning")).toBeNull();
  });

  test("the notice sits above the tab bar, so it is on every tab", () => {
    // Testing the POSITION, not just the presence: rendered inside one tab's
    // panel it would vanish the moment someone clicked MCPS — the tab that
    // needed it most.
    render(<Capabilities provider="gemini" />);
    const notice = screen.getByTestId("tool-transport-warning");
    const tablist = screen.getByRole("tablist");
    expect(notice.compareDocumentPosition(tablist) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    // And it is not inside any tab panel, which is the shape that would make it
    // disappear on tab change.
    expect(notice.closest('[role="tabpanel"]')).toBeNull();
  });

  test("it is still there after switching to the MCPS tab", async () => {
    // The behavioural version of the position test. MCPS is the tab where
    // someone ticks "Allow Arslan (all tools)" on a server whose tools will
    // never be transported — the most confident false claim in the app — so
    // "the notice survives that click" is the thing worth asserting, not just
    // where it sits in the DOM.
    render(<Capabilities provider="gemini" />);
    expect(screen.getByTestId("tool-transport-warning")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /MCPs/i }));
    await waitFor(() =>
      expect(screen.getByTestId("tool-transport-warning")).toBeInTheDocument());
  });
});
