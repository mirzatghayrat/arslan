import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
  setMcpServerHost: vi.fn(),
  wireMcpTool: vi.fn(),
}));

vi.mock("../api/catalog", () => ({
  getMcpCatalog: vi.fn(),
}));

import { api } from "../api/client";
import * as discovery from "../api/discovery";
import * as mcp from "../api/mcp";
import * as catalog from "../api/catalog";
import Capabilities from "../components/Capabilities";

// Mirrors GET /mcp/catalog (server/mcp/catalog.py) — 9 preset connectors, "Memory" among
// the credential-free ones. Used to keep the chip-count + card-render assertions grounded
// in real fetched data (the old static data/ preset module was deleted in Task 4).
const CATALOG_FIXTURE = [
  { key: "fetch", label: "Fetch", transport: "stdio", command: "uvx", args: ["mcp-server-fetch"], url: null, runtime: "python", description: "Fetch a URL and convert it to clean markdown.", one_click: true, env: [] },
  { key: "memory", label: "Memory", transport: "stdio", command: "npx", args: ["-y", "@modelcontextprotocol/server-memory"], url: null, runtime: "node", description: "Persistent knowledge-graph memory (stored locally).", one_click: true, env: [] },
  { key: "sequential-thinking", label: "Sequential Thinking", transport: "stdio", command: "npx", args: ["-y", "@modelcontextprotocol/server-sequential-thinking"], url: null, runtime: "node", description: "A structured step-by-step reasoning scaffold.", one_click: true, env: [] },
  { key: "time", label: "Time", transport: "stdio", command: "uvx", args: ["mcp-server-time"], url: null, runtime: "python", description: "Current time and timezone conversion.", one_click: true, env: [] },
  { key: "filesystem", label: "Filesystem", transport: "stdio", command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem"], url: null, runtime: "node", description: "Read and write files under a directory you choose.", one_click: true, env: [] },
  { key: "git", label: "Git", transport: "stdio", command: "uvx", args: ["mcp-server-git", "--repository"], url: null, runtime: "python", description: "Read, search, and commit a local git repository.", one_click: true, env: [] },
  { key: "everything", label: "Everything", transport: "stdio", command: "npx", args: ["-y", "@modelcontextprotocol/server-everything"], url: null, runtime: "node", description: "Reference server with sample tools.", one_click: true, env: [] },
  { key: "brave-search", label: "Brave Search", transport: "stdio", command: "npx", args: ["-y", "@modelcontextprotocol/server-brave-search"], url: null, runtime: "node", description: "Web search via the Brave Search API.", one_click: false, env: [{ name: "BRAVE_API_KEY", description: "A Brave Search API key.", get_it_url: "https://brave.com/search/api/", paid: false }] },
  { key: "github", label: "GitHub", transport: "stdio", command: "npx", args: ["-y", "@modelcontextprotocol/server-github"], url: null, runtime: "node", description: "GitHub repo / issue / PR access.", one_click: false, env: [{ name: "GITHUB_PERSONAL_ACCESS_TOKEN", description: "A GitHub personal access token.", get_it_url: "https://github.com/settings/tokens", paid: false }] },
];

beforeEach(() => {
  vi.clearAllMocks();
  (api.getRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({ toolsets: [], skills: [] });
  (api.listSpawns as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.listSkillCandidates as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (api.getCuratorReview as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (discovery.listCandidates as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (discovery.searchRepos as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (mcp.listMcpServers as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (catalog.getMcpCatalog as ReturnType<typeof vi.fn>).mockResolvedValue(CATALOG_FIXTURE);
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
    // Chip row derived from real data: both counts are fetched (presets via GET /mcp/catalog,
    // registered servers via GET /mcp/servers) — wait for the async catalog fetch to resolve.
    const recommendedChip = screen.getByRole("button", { name: /capabilities\.chips\.recommended/ });
    await waitFor(() => expect(recommendedChip).toHaveTextContent(/9/)); // CATALOG_FIXTURE.length
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
    expect(screen.getByPlaceholderText("capabilities.import.repo_placeholder")).toBeInTheDocument();
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
