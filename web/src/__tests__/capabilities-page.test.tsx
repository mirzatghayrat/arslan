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
  exposeMcpServer: vi.fn(),
  reconnectMcpServer: vi.fn(),
  listMcpTools: vi.fn(),
  setMcpServerHost: vi.fn(),
  wireMcpTool: vi.fn(),
}));


vi.mock("../api/capabilities", () => ({
  capabilitiesApi: { list: vi.fn(async () => []), switch: vi.fn(), deleteRow: vi.fn(), source: vi.fn(),
    exportNotice: vi.fn(async () => ({ count: 0 })), exportNoticeSeen: vi.fn() },
}));

import { api } from "../api/client";
import * as mcp from "../api/mcp";
import Capabilities from "../components/Capabilities";

beforeEach(() => {
  vi.clearAllMocks();
  (api.getRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({ toolsets: [], skills: [] });
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

  it("C7c-4: no legacy experts section and no expert skill catalog", async () => {
    // The old `experts` slot is gone: passing it (as App used to) renders nothing extra.
    const old = { experts: <div>Expert workspace</div> } as Record<string, unknown>;
    render(<Capabilities {...old} />);
    expect(await screen.findByText("capabilityList.intro")).toBeInTheDocument();
    expect(screen.queryByTestId("legacy-experts")).toBeNull();
    expect(screen.queryByText("workspace.legacyExperts")).not.toBeInTheDocument();
    expect(screen.queryByText("Expert workspace")).not.toBeInTheDocument();
    expect(api.getRegistry).not.toHaveBeenCalled();
  });

  it("CAP1a: no Discover, no search hero, no saved candidates; no official-directory row", () => {
    render(<Capabilities />);
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
