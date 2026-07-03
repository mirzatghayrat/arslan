import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// i18n passthrough
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("../api/client", () => ({
  api: {
    getRegistry: vi.fn(),
    listSpawns: vi.fn(),
    ingestKnowledgeText: vi.fn(),
    listSkillCandidates: vi.fn(),
    getCuratorReview: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
  API_BASE: "",
}));

vi.mock("../api/discovery", () => ({
  listCandidates: vi.fn(),
  refreshCandidate: vi.fn(),
  deleteCandidate: vi.fn(),
  generateSkill: vi.fn(),
  createSkill: vi.fn(),
  searchRepos: vi.fn(),
  evaluateRepo: vi.fn(),
  saveCandidate: vi.fn(),
  scanSkills: vi.fn(),
  importSkill: vi.fn(),
}));

vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn(),
  addMcpServer: vi.fn(),
  connectMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
  exposeMcpServer: vi.fn(),
  reconnectMcpServer: vi.fn(),
  listMcpTools: vi.fn(),
  setMcpToolHost: vi.fn(),
  wireMcpTool: vi.fn(),
}));

import { api } from "../api/client";
import * as discovery from "../api/discovery";
import * as mcp from "../api/mcp";
import Capabilities from "../components/Capabilities";

beforeEach(() => {
  vi.clearAllMocks();
  (api.getRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({ toolsets: [], skills: [] });
  (api.listSpawns as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.listSkillCandidates as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.getCuratorReview as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (discovery.listCandidates as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (discovery.searchRepos as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (mcp.listMcpServers as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

describe("Capabilities page structure (one tab bar, Discover first)", () => {
  it("renders one tab bar with all six tabs, Discover first", () => {
    render(<Capabilities />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((el) => el.textContent)).toEqual([
      "capabilities.tabs.discover",
      "capabilities.tabs.tools",
      "capabilities.tabs.skills",
      "capabilities.tabs.forge",
      "capabilities.tabs.mcps",
      "capabilities.tabs.saved",
    ]);
  });

  it("DISCOVER is the default tab and holds the Tool-Hub hero (input + Research)", () => {
    render(<Capabilities />);
    expect(screen.getByRole("tab", { name: "capabilities.tabs.discover" }))
      .toHaveAttribute("aria-selected", "true");
    expect(screen.getByPlaceholderText("capabilities.hero.placeholder")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /capabilities\.hero\.research/ })).toBeInTheDocument();
  });

  it("the hero lives only inside the Discover tab (gone on other tabs)", () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.tools" }));
    expect(screen.queryByPlaceholderText("capabilities.hero.placeholder")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.discover" }));
    expect(screen.getByPlaceholderText("capabilities.hero.placeholder")).toBeInTheDocument();
  });

  it("MCPS tab contains the rehomed Recommended one-click section", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.mcps" }));
    expect(screen.getByText("capabilities.sections.recommended_mcp")).toBeInTheDocument();
    // RecommendedMcp preset cards render inside the tab
    expect(await screen.findByText("Memory")).toBeInTheDocument();
  });

  it("MCPS chips filter between the presets section and the server list; all resets", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.mcps" }));
    // Chip row derived from real data: presets count (static) + registered servers count (fetched)
    const recommendedChip = screen.getByRole("button", { name: /capabilities\.chips\.recommended/ });
    expect(recommendedChip).toHaveTextContent(/9/); // MCP_PRESETS.length
    expect(screen.getByRole("button", { name: /capabilities\.chips\.registered/ })).toBeInTheDocument();
    // Both sections visible by default (all)
    expect(screen.getByText("capabilities.sections.recommended_mcp")).toBeInTheDocument();
    expect(await screen.findByText("MCP Servers")).toBeInTheDocument();
    // registered → presets section hidden, server list stays
    fireEvent.click(screen.getByRole("button", { name: /capabilities\.chips\.registered/ }));
    expect(screen.queryByText("capabilities.sections.recommended_mcp")).not.toBeInTheDocument();
    expect(screen.getByText("MCP Servers")).toBeInTheDocument();
    // recommended → server list hidden, presets stay
    fireEvent.click(recommendedChip);
    expect(screen.getByText("capabilities.sections.recommended_mcp")).toBeInTheDocument();
    expect(screen.queryByText("MCP Servers")).not.toBeInTheDocument();
    // all → both back
    fireEvent.click(screen.getByRole("button", { name: /capabilities\.chips\.all/ }));
    expect(screen.getByText("capabilities.sections.recommended_mcp")).toBeInTheDocument();
    expect(screen.getByText("MCP Servers")).toBeInTheDocument();
  });

  it("SKILLS tab contains the rehomed Import-skills form + registry catalog", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.skills" }));
    expect(screen.getByText("capabilities.sections.import_skills")).toBeInTheDocument();
    // SkillImportPanel's owner/repo scan input
    expect(screen.getByPlaceholderText("owner/repo")).toBeInTheDocument();
  });

  it("SKILL FORGE tab shows the two-entry-modes header + candidate list", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.forge" }));
    expect(screen.getByText("forge.modes.title")).toBeInTheDocument();
    expect(screen.getByText("forge.modes.a_title")).toBeInTheDocument();
    expect(screen.getByText("forge.modes.b_title")).toBeInTheDocument();
    expect(await screen.findByText("forge.list.empty")).toBeInTheDocument();
  });

  it("clicking Saved tab shows SavedCandidates content", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.saved" }));
    // SavedCandidates renders "Refresh list" button
    expect(await screen.findByRole("button", { name: /refresh list/i })).toBeInTheDocument();
  });

  it("page scrolls as a whole (overflow-y-auto shell)", () => {
    const { container } = render(<Capabilities />);
    const scrollContainer = container.querySelector(".overflow-y-auto");
    expect(scrollContainer).not.toBeNull();
  });
});
