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
  },
  ApiError: class ApiError extends Error {},
  API_BASE: "",
}));

vi.mock("../api/discovery", () => ({
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
  capabilitiesApi: { list: vi.fn(async () => []), switch: vi.fn(), deleteRow: vi.fn(), source: vi.fn() },
}));

import { api } from "../api/client";
import * as mcp from "../api/mcp";
import Capabilities from "../components/Capabilities";

beforeEach(() => {
  vi.clearAllMocks();
  (api.getRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({ toolsets: [], skills: [] });
  (api.listSpawns as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (mcp.listMcpServers as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

describe("Capabilities page: one list (v0.1.64 CAP3a)", () => {
  it("has no tabs: the one list, built in / skills / connections, opens straight away", async () => {
    render(<Capabilities />);
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(await screen.findByText("capabilityList.intro")).toBeInTheDocument();
    expect(screen.getByTestId("cap-add-link")).toBeInTheDocument();
  });

  it("legacy experts keep their own section below the list, with the catalog that equips them, only when there are any", async () => {
    const { unmount } = render(<Capabilities />);
    expect(screen.queryByTestId("legacy-experts")).toBeNull();
    unmount();
    render(<Capabilities experts={<div>Expert workspace</div>} />);
    const section = screen.getByTestId("legacy-experts");
    expect(section).toHaveTextContent("workspace.legacyExperts");
    expect(section).toHaveTextContent("Expert workspace");
    await waitFor(() => expect(api.getRegistry).toHaveBeenCalled());
  });

  it("CAP1a: no Discover, no search hero, no saved candidates; no official-directory row", () => {
    render(<Capabilities experts={<div>Expert workspace</div>} />);
    expect(screen.queryByPlaceholderText("capabilities.hero.placeholder")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "capabilities.tabs.saved" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("cap-add-discover")).toBeNull();
    expect(screen.queryByTestId("cap-add-mcps")).toBeNull();
    expect(screen.queryByText("capabilities.sections.recommended_mcp")).not.toBeInTheDocument();
  });

  it("Paste a link opens the skill import panel in a sheet", async () => {
    render(<Capabilities />);
    fireEvent.click(screen.getByTestId("cap-add-link"));
    expect(await screen.findByTestId("cap-link-sheet")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("capabilities.import.repo_placeholder")).toBeInTheDocument();
  });

  it("v0.1.64 CAP2a: no Create skill page; the add-other row says to ask for it in a conversation", async () => {
    render(<Capabilities />);
    const row = await screen.findByTestId("cap-add-method");
    expect(row.textContent).toContain("capabilityList.addMethodSay");
    expect(row.tagName).not.toBe("BUTTON");
    expect(row.querySelector("button")).toBeNull();                 // nothing to open
    expect(screen.queryByTestId("cap-add-forge")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "workspace.createSkill" })).not.toBeInTheDocument();
  });

  it("page scrolls as a whole (overflow-y-auto shell)", () => {
    const { container } = render(<Capabilities />);
    const scrollContainer = container.querySelector(".overflow-y-auto");
    expect(scrollContainer).not.toBeNull();
  });
});
