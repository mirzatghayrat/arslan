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
 * The insertion is ABOVE the list on purpose: one place for every section,
 * including the connections, which is where the most confident false claim in
 * the app lives (v0.1.64 CAP3a: one list, no tabs).
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach } from "vitest";
import Capabilities from "../components/Capabilities";
import * as transport from "../lib/toolTransport";
import { capabilitiesApi } from "../api/capabilities";
import "../i18n";

vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn(async () => []),
  addMcpServer: vi.fn(),
  connectMcpServer: vi.fn(),
  exposeMcpServer: vi.fn(),
}));

describe("the Capability Library says when equipping will have no effect", () => {
  beforeEach(() => vi.restoreAllMocks());

  test("a provider that cannot carry tools is called out", () => {
    vi.spyOn(transport, "toolTransportState").mockReturnValue("unsupported");
    render(<Capabilities provider="test-unsupported" />);
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
    render(<Capabilities provider="unknown-provider" />);
    expect(screen.getByTestId("tool-transport-provider")).toHaveTextContent("unknown-provider");
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

  test("the notice sits above the list, so it is over every section", () => {
    // Testing the POSITION, not just the presence: rendered inside one section
    // it would scroll away or be folded with it — the connections needed it most.
    render(<Capabilities provider="unknown-provider" />);
    const notice = screen.getByTestId("tool-transport-warning");
    const heading = screen.getByRole("heading", { level: 1 });
    expect(notice.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(notice.closest("section")).toBeNull();
  });

  test("it is still there while a connection is being added by hand", async () => {
    // The behavioural version of the position test. Adding a server and ticking
    // "Allow Arslan (all tools)" on one whose tools will never be transported is
    // the most confident false claim in the app, so "the notice survives opening
    // that sheet" is the thing worth asserting, not just where it sits in the DOM.
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([]);
    render(<Capabilities provider="unknown-provider" />);
    expect(screen.getByTestId("tool-transport-warning")).toBeInTheDocument();
    fireEvent.click(await screen.findByTestId("cap-add-manual"));
    expect(await screen.findByTestId("cap-manual-sheet")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("tool-transport-warning")).toBeInTheDocument());
  });
});
