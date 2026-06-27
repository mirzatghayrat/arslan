import { render, screen } from "@testing-library/react";
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
    expect(screen.getByText("Shell")).toBeTruthy();
    expect(screen.getAllByText("assignable").length).toBeGreaterThanOrEqual(1);
  });

  it("lists skills in skills mode", async () => {
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Writer");
    expect(screen.getByText("content")).toBeTruthy();
  });
});
