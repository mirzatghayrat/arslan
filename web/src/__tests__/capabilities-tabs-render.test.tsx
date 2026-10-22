import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
vi.mock("../api/professionalMethods", () => ({ professionalMethodsApi: { list: vi.fn(async () => []) } }));

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


vi.mock("../api/capabilities", () => ({
  capabilitiesApi: { list: vi.fn(async () => []), switch: vi.fn() },
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

describe("Capabilities page structure and legacy feature reachability", () => {
  it("0.1.55: opens on the switches; the legacy experts tab exists only for those who have experts, last", () => {
    render(<Capabilities experts={<div>Expert workspace</div>} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((el) => el.textContent)).toEqual([
      "capabilityList.tab",
      "workspace.skillsWorkflows",
      "workspace.connections",
      "capabilities.tabs.discover",
      "workspace.legacyExperts",
    ]);
    expect(screen.getByRole("tab", { name: "capabilityList.tab" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Expert workspace")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "workspace.legacyExperts" }));
    expect(screen.getByText("Expert workspace")).toBeInTheDocument();
  });

  it("without experts there is no experts tab, and no legacy spawn toolsets tab", () => {
    render(<Capabilities />);
    const names = screen.getAllByRole("tab").map((el) => el.textContent);
    expect(names).not.toContain("workspace.legacyExperts");
    expect(names).not.toContain("capabilities.tabs.tools");
  });

  it("Discover holds the Tool-Hub hero (input + Research)", () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.discover" }));
    expect(screen.getByPlaceholderText("capabilities.hero.placeholder")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /capabilities\.hero\.research/ })).toBeInTheDocument();
  });

  it("the hero lives only inside the Discover tab (gone on other tabs)", () => {
    render(<Capabilities />);
    expect(screen.queryByPlaceholderText("capabilities.hero.placeholder")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.discover" }));
    expect(screen.getByPlaceholderText("capabilities.hero.placeholder")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "workspace.skillsWorkflows" }));
    expect(screen.queryByPlaceholderText("capabilities.hero.placeholder")).not.toBeInTheDocument();
  });

  it("Add from elsewhere › MCP directory reaches the server list (0.1.63 C9b: no recommended presets)", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByTestId("cap-add-mcps"));
    expect(await screen.findByText("connectionsUI.servers")).toBeInTheDocument();
    expect(screen.queryByText("capabilities.sections.recommended_mcp")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /capabilities\.chips\.recommended/ })).not.toBeInTheDocument();
  });

  it("SKILLS tab contains the rehomed Import-skills form + registry catalog", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "workspace.skillsWorkflows" }));
    expect(screen.getByText("capabilities.sections.import_skills")).toBeInTheDocument();
    // SkillImportPanel's owner/repo scan input
    expect(screen.getByPlaceholderText("capabilities.import.repo_placeholder")).toBeInTheDocument();
  });

  it("Create skill opens the original forge without a separate primary tab", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "workspace.skillsWorkflows" }));
    fireEvent.click(screen.getByRole("button", { name: "workspace.createSkill" }));
    expect(screen.getByText("forge.modes.title")).toBeInTheDocument();
    expect(screen.getByText("forge.modes.a_title")).toBeInTheDocument();
    expect(screen.getByText("forge.modes.b_title")).toBeInTheDocument();
    expect(await screen.findByText("forge.list.empty")).toBeInTheDocument();
  });

  it("Saved is a Discover filter and retains SavedCandidates content", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByRole("tab", { name: "capabilities.tabs.discover" }));
    fireEvent.click(screen.getByRole("button", { name: "capabilities.tabs.saved" }));
    // SavedCandidates renders "Refresh list" button
    expect(await screen.findByRole("button", { name: "connectionsUI.refreshList" })).toBeInTheDocument();
  });

  it("page scrolls as a whole (overflow-y-auto shell)", () => {
    const { container } = render(<Capabilities />);
    const scrollContainer = container.querySelector(".overflow-y-auto");
    expect(scrollContainer).not.toBeNull();
  });

  it("connections are a tab here (0.1.48: no separate Connections page)", () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByTestId("cap-add-mcps"));
    expect(screen.getByRole("tab", { name: "workspace.connections" }).getAttribute("aria-selected")).toBe("true");
  });
});
