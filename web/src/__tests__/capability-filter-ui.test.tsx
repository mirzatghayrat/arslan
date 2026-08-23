/**
 * The filter as the user meets it, on the TOOLS tab.
 *
 * The rules are tested next door without rendering; this asserts the two things
 * only the UI can get wrong — that the count is shown (so an empty result never
 * reads as an empty library) and that a card surfaced only by an inner tool says
 * so.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach } from "vitest";
import CapabilityCatalog from "../components/CapabilityCatalog";
import { api } from "../api/client";
import "../i18n";

vi.mock("../api/client", () => ({ api: { getRegistry: vi.fn() } }));

const CATALOG = {
  toolsets: [
    {
      key: "browsing", name: "Browsing", description: "Read pages.",
      tier: "safe", status: "wired", assignable: true,
      tools: [
        { key: "web_search", name: "web_search", description: "Search the web.", tier: "safe", status: "wired" },
      ],
    },
    {
      key: "file_operations", name: "File Operations", description: "Read files.",
      tier: "safe", status: "wired", assignable: true, tools: [],
    },
  ],
  skills: [],
};

describe("filtering the tools tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getRegistry).mockResolvedValue(CATALOG as never);
  });

  test("everything is listed before you type", async () => {
    render(<CapabilityCatalog kind="tools" />);
    expect(await screen.findByText("Browsing")).toBeInTheDocument();
    expect(screen.getByText("File Operations")).toBeInTheDocument();
    // No count while idle: a permanent "2 of 2" is noise.
    expect(screen.queryByTestId("tools-filter-count")).toBeNull();
  });

  test("typing narrows the list", async () => {
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Browsing");
    fireEvent.change(screen.getByTestId("tools-filter"), { target: { value: "file" } });
    await waitFor(() => expect(screen.queryByText("Browsing")).toBeNull());
    expect(screen.getByText("File Operations")).toBeInTheDocument();
  });

  test("searching for a TOOL surfaces the set holding it, and says which", async () => {
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Browsing");
    fireEvent.change(screen.getByTestId("tools-filter"), { target: { value: "web_search" } });
    await waitFor(() => expect(screen.getByText("Browsing")).toBeInTheDocument());
    expect(screen.queryByText("File Operations")).toBeNull();
    expect(screen.getByTestId("toolset-matched-browsing")).toHaveTextContent("web_search");
  });

  test("a card matched on its own name gets no extra line", async () => {
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Browsing");
    fireEvent.change(screen.getByTestId("tools-filter"), { target: { value: "Browsing" } });
    await waitFor(() => expect(screen.getByText("Browsing")).toBeInTheDocument());
    expect(screen.queryByTestId("toolset-matched-browsing")).toBeNull();
  });

  test("hiding everything says how much was hidden", async () => {
    // The load-bearing one. Without the count, a typo produces a screen that is
    // indistinguishable from having no tools installed.
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Browsing");
    fireEvent.change(screen.getByTestId("tools-filter"), { target: { value: "zzzz" } });
    await waitFor(() =>
      expect(screen.getByTestId("empty-capabilities-filtered")).toBeInTheDocument());
    expect(screen.getByTestId("tools-filter-count")).toHaveTextContent("0");
    expect(screen.getByTestId("tools-filter-count")).toHaveTextContent("2");
  });

  test("clearing brings everything back", async () => {
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Browsing");
    fireEvent.change(screen.getByTestId("tools-filter"), { target: { value: "zzzz" } });
    await waitFor(() => expect(screen.queryByText("Browsing")).toBeNull());
    fireEvent.click(screen.getByTestId("tools-filter-clear"));
    await waitFor(() => expect(screen.getByText("Browsing")).toBeInTheDocument());
    expect(screen.getByText("File Operations")).toBeInTheDocument();
  });
});
