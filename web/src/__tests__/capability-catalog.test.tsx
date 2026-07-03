import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CapabilityCatalog from "../components/CapabilityCatalog";

vi.mock("../api/client", () => ({ api: { getRegistry: vi.fn() } }));
import { api } from "../api/client";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  m.getRegistry.mockResolvedValue({
    toolsets: [
      { key: "web", name: "Web Tools", description: "Search the web", tier: "safe", status: "wired", assignable: true, tools: [] },
      { key: "shell", name: "Shell", description: "Run shell commands", tier: "orchestrator", status: "wired", assignable: false, tools: [] },
    ],
    skills: [
      { key: "writer", name: "Writer", category: "content", description: "Write copy", tier: "safe", status: "registered", assignable: true },
    ],
  });
});

describe("CapabilityCatalog", () => {
  it("lists toolsets with a badge in tools mode (both groups visible by default)", async () => {
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Web Tools");
    // Shell is non-assignable → shown under the locked group (default = all)
    expect(screen.getByText("Shell")).toBeTruthy();
    expect(screen.getAllByText("assignable").length).toBeGreaterThanOrEqual(1);
  });

  it("lists skills in skills mode", async () => {
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Writer");
    expect(screen.getAllByText(/content/i).length).toBeGreaterThanOrEqual(1);
  });

  it("tools: hides infeasible; status chips derived from data filter the groups", async () => {
    const cat = { toolsets: [
      { key: "a", name: "Alpha", description: "d", tier: "safe", status: "wired", assignable: true, tools: [] },
      { key: "b", name: "Bravo", description: "d", tier: "orchestrator", status: "registered", assignable: false, tools: [] },
      { key: "c", name: "Charlie", description: "d", tier: "orchestrator", status: "infeasible", assignable: false, tools: [] },
    ], skills: [] };
    (api.getRegistry as any).mockResolvedValue(cat);
    render(<CapabilityCatalog kind="tools" />);
    expect(await screen.findByText("Alpha")).toBeInTheDocument();   // assignable, shown
    expect(screen.getByText("Bravo")).toBeInTheDocument();          // locked, shown under all
    expect(screen.queryByText("Charlie")).not.toBeInTheDocument();  // infeasible, hidden

    // Chips carry counts derived from the real data (Charlie excluded)
    const allChip = screen.getByRole("button", { name: /capabilities\.chips\.all/ });
    const assignableChip = screen.getByRole("button", { name: /assignable_group/ });
    const lockedChip = screen.getByRole("button", { name: /locked_group/ });
    expect(allChip).toHaveTextContent("2");
    expect(assignableChip).toHaveTextContent("1");
    expect(lockedChip).toHaveTextContent("1");

    // assignable chip → locked group filtered out
    fireEvent.click(assignableChip);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.queryByText("Bravo")).not.toBeInTheDocument();
    // locked chip → assignable group filtered out
    fireEvent.click(lockedChip);
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    expect(screen.getByText("Bravo")).toBeInTheDocument();
    // all resets
    fireEvent.click(allChip);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Bravo")).toBeInTheDocument();
  });

  it("skills: hides infeasible; category chips with counts filter, all resets", async () => {
    const cat = { toolsets: [], skills: [
      { key: "s1", name: "S1", category: "creative", description: "d", tier: "safe", status: "registered", assignable: true },
      { key: "s2", name: "S2", category: "research", description: "d", tier: "safe", status: "registered", assignable: true },
      { key: "s3", name: "S3", category: "creative", description: "d", tier: "orchestrator", status: "infeasible", assignable: false },
    ] };
    (api.getRegistry as any).mockResolvedValue(cat);
    render(<CapabilityCatalog kind="skills" />);
    expect(await screen.findByText("S1")).toBeInTheDocument();
    expect(screen.getByText("S2")).toBeInTheDocument();
    expect(screen.queryByText("S3")).not.toBeInTheDocument();        // infeasible hidden

    // Category chips derived from the real registry categories, with counts
    // (S3 is infeasible → creative counts 1, not 2)
    const creativeChip = screen.getByRole("button", { name: /creative/ });
    const researchChip = screen.getByRole("button", { name: /research/ });
    const allChip = screen.getByRole("button", { name: /capabilities\.chips\.all/ });
    expect(allChip).toHaveTextContent("2");
    expect(creativeChip).toHaveTextContent("1");
    expect(researchChip).toHaveTextContent("1");

    // Clicking a category chip filters to that category
    fireEvent.click(creativeChip);
    expect(screen.getByText("S1")).toBeInTheDocument();
    expect(screen.queryByText("S2")).not.toBeInTheDocument();
    fireEvent.click(researchChip);
    expect(screen.queryByText("S1")).not.toBeInTheDocument();
    expect(screen.getByText("S2")).toBeInTheDocument();
    // all resets to every category (sub-headers back)
    fireEvent.click(allChip);
    expect(screen.getByText("S1")).toBeInTheDocument();
    expect(screen.getByText("S2")).toBeInTheDocument();
  });
});
