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
  it("lists toolsets with a badge in tools mode", async () => {
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Web Tools");
    // Shell is non-assignable → inside the collapsed locked group; expand to see it
    fireEvent.click(screen.getByRole("button", { name: /locked|orchestrator|未启用/i }));
    expect(screen.getByText("Shell")).toBeTruthy();
    expect(screen.getAllByText("assignable").length).toBeGreaterThanOrEqual(1);
  });

  it("lists skills in skills mode", async () => {
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Writer");
    expect(screen.getByText(/content/i)).toBeTruthy();
  });

  it("tools: hides infeasible, groups assignable vs locked", async () => {
    const cat = { toolsets: [
      { key: "a", name: "Alpha", description: "d", tier: "safe", status: "wired", assignable: true, tools: [] },
      { key: "b", name: "Bravo", description: "d", tier: "orchestrator", status: "registered", assignable: false, tools: [] },
      { key: "c", name: "Charlie", description: "d", tier: "orchestrator", status: "infeasible", assignable: false, tools: [] },
    ], skills: [] };
    (api.getRegistry as any).mockResolvedValue(cat);
    render(<CapabilityCatalog kind="tools" />);
    expect(await screen.findByText("Alpha")).toBeInTheDocument();   // assignable, shown
    expect(screen.queryByText("Charlie")).not.toBeInTheDocument();  // infeasible, hidden
    // "Bravo" is locked → present but inside the (collapsed) locked group; expand it
    const lockedToggle = screen.getByRole("button", { name: /locked|orchestrator|未启用/i });
    fireEvent.click(lockedToggle);
    expect(await screen.findByText("Bravo")).toBeInTheDocument();
  });

  it("skills: groups by category, hides infeasible", async () => {
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
    expect(screen.getByText(/creative/i)).toBeInTheDocument();       // category sub-header
    expect(screen.getByText(/research/i)).toBeInTheDocument();
  });
});
