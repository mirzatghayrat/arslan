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
  API_BASE: "",
}));

vi.mock("../api/discovery", () => ({
  listCandidates: vi.fn(),
  refreshCandidate: vi.fn(),
  deleteCandidate: vi.fn(),
  generateSkill: vi.fn(),
  createSkill: vi.fn(),
  searchRepos: vi.fn(),
  evalRepo: vi.fn(),
  saveCandidate: vi.fn(),
}));

import { api } from "../api/client";
import * as discovery from "../api/discovery";
import Capabilities from "../components/Capabilities";

beforeEach(() => {
  vi.clearAllMocks();
  (api.getRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({ toolsets: [], skills: [] });
  (discovery.listCandidates as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (discovery.searchRepos as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

describe("Capabilities tabs render", () => {
  it("renders a Saved tab button", async () => {
    render(<Capabilities />);
    // CapabilityTabs renders tab buttons with role="tab"
    const savedTab = await screen.findByRole("tab", { name: /saved/i });
    expect(savedTab).toBeInTheDocument();
  });

  it("clicking Saved tab shows SavedCandidates content", async () => {
    render(<Capabilities />);
    const savedTab = await screen.findByRole("tab", { name: /saved/i });
    fireEvent.click(savedTab);
    // SavedCandidates renders "Refresh list" button
    expect(await screen.findByRole("button", { name: /refresh list/i })).toBeInTheDocument();
  });

  it("tab content is wrapped in an overflow-y-auto scroll container", () => {
    const { container } = render(<Capabilities />);
    const scrollContainer = container.querySelector(".overflow-y-auto");
    expect(scrollContainer).not.toBeNull();
  });
});
