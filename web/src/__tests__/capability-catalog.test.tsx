import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CapabilityCatalog from "../components/CapabilityCatalog";

// i18n passthrough — t() returns the key so assertions are locale-independent.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("../api/client", () => ({ api: { getRegistry: vi.fn(), listSpawns: vi.fn(), updateEquipment: vi.fn() } }));
import { api } from "../api/client";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const CATALOG = {
  toolsets: [
    { key: "web", name: "Web Tools", description: "Search the web", tier: "safe", status: "wired", assignable: true, tools: [] },
    { key: "discord", name: "Discord", description: "Fetch messages", tier: "safe", status: "registered", assignable: false, tools: [] },
    { key: "shell", name: "Shell", description: "Run shell commands", tier: "orchestrator", status: "registered", assignable: false, tools: [] },
    { key: "ghost", name: "Ghost", description: "gone", tier: "orchestrator", status: "infeasible", assignable: false, tools: [] },
  ],
  skills: [
    { key: "writer", name: "Writer", category: "content", description: "Write copy", tier: "safe", status: "registered", assignable: true },
    { key: "planner", name: "Planner", category: "ops", description: "Plan work", tier: "safe", status: "registered", assignable: true },
    { key: "airtable", name: "Airtable", category: "productivity", description: "Bases", tier: "safe", status: "registered", assignable: false },
    { key: "claude-code", name: "Claude Code", category: "agents", description: "Delegate coding", tier: "orchestrator", status: "registered", assignable: false },
    { key: "dead", name: "Dead", category: "content", description: "gone", tier: "safe", status: "infeasible", assignable: false },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.getRegistry.mockResolvedValue(CATALOG);
  m.listSpawns.mockResolvedValue([]);
});

const chipBtn = (re: RegExp) => screen.getByRole("button", { name: re });

describe("CapabilityCatalog — usable-first availability chips", () => {
  it("tools: default 可用 chip shows only assignable toolsets (hollow + orchestrator hidden)", async () => {
    render(<CapabilityCatalog kind="tools" />);
    expect(await screen.findByText("Web Tools")).toBeInTheDocument();
    expect(screen.queryByText("Discord")).not.toBeInTheDocument();
    expect(screen.queryByText("Shell")).not.toBeInTheDocument();
    expect(screen.queryByText("Ghost")).not.toBeInTheDocument(); // infeasible always hidden
    // usable chip is the default (active)
    expect(chipBtn(/capabilities\.chips\.usable/)).toHaveAttribute("aria-pressed", "true");
    // counts derived from real data (infeasible excluded)
    expect(chipBtn(/capabilities\.chips\.usable/)).toHaveTextContent("1");
    expect(chipBtn(/capabilities\.chips\.unimplemented/)).toHaveTextContent("1");
    expect(chipBtn(/capabilities\.chips\.arslan_only/)).toHaveTextContent("1");
    expect(chipBtn(/capabilities\.chips\.all/)).toHaveTextContent("3");
  });

  it("tools: 未实装 chip reveals hollow items muted with the honest placeholder note", async () => {
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Web Tools");
    fireEvent.click(chipBtn(/capabilities\.chips\.unimplemented/));
    expect(screen.getByText("Discord")).toBeInTheDocument();
    expect(screen.queryByText("Web Tools")).not.toBeInTheDocument();
    expect(screen.getByText("capabilities.catalog.unimplemented_note")).toBeInTheDocument();
    // no fake equip affordance on hollow rows
    expect(screen.queryByText("capabilities.equip.action")).not.toBeInTheDocument();
  });

  it("tools: 仅 Arslan chip shows orchestrator items with the security explainer", async () => {
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Web Tools");
    fireEvent.click(chipBtn(/capabilities\.chips\.arslan_only/));
    expect(screen.getByText("Shell")).toBeInTheDocument();
    expect(screen.getByText("capabilities.catalog.orchestrator_note")).toBeInTheDocument();
    expect(screen.queryByText("capabilities.equip.action")).not.toBeInTheDocument();
  });

  it("tools: 全部 chip shows everything (except infeasible) with badges", async () => {
    render(<CapabilityCatalog kind="tools" />);
    await screen.findByText("Web Tools");
    fireEvent.click(chipBtn(/capabilities\.chips\.all/));
    expect(screen.getByText("Web Tools")).toBeInTheDocument();
    expect(screen.getByText("Discord")).toBeInTheDocument();
    expect(screen.getByText("Shell")).toBeInTheDocument();
    expect(screen.queryByText("Ghost")).not.toBeInTheDocument();
    expect(screen.getByText("assignable")).toBeInTheDocument();
    expect(screen.getByText("catalog")).toBeInTheDocument();
    expect(screen.getByText("orchestrator/registered")).toBeInTheDocument();
  });

  it("skills: default 可用 chip shows only assignable skills; category chips filter within usable", async () => {
    render(<CapabilityCatalog kind="skills" />);
    expect(await screen.findByText("Writer")).toBeInTheDocument();
    expect(screen.getByText("Planner")).toBeInTheDocument();
    expect(screen.queryByText("Airtable")).not.toBeInTheDocument();
    expect(screen.queryByText("Claude Code")).not.toBeInTheDocument();
    expect(screen.queryByText("Dead")).not.toBeInTheDocument();
    // category chips derived from the usable pool only (no productivity/agents chip)
    expect(screen.queryByRole("button", { name: /productivity/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /agents/ })).not.toBeInTheDocument();
    fireEvent.click(chipBtn(/content/));
    expect(screen.getByText("Writer")).toBeInTheDocument();
    expect(screen.queryByText("Planner")).not.toBeInTheDocument();
    fireEvent.click(chipBtn(/ops/));
    expect(screen.queryByText("Writer")).not.toBeInTheDocument();
    expect(screen.getByText("Planner")).toBeInTheDocument();
  });

  it("skills: 未实装 chip reveals hollow skill with honest note; 仅 Arslan shows orchestrator skill + explainer", async () => {
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Writer");
    fireEvent.click(chipBtn(/capabilities\.chips\.unimplemented/));
    expect(screen.getByText("Airtable")).toBeInTheDocument();
    expect(screen.queryByText("Writer")).not.toBeInTheDocument();
    expect(screen.getByText("capabilities.catalog.unimplemented_note")).toBeInTheDocument();
    fireEvent.click(chipBtn(/capabilities\.chips\.arslan_only/));
    expect(screen.getByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText("capabilities.catalog.orchestrator_note")).toBeInTheDocument();
  });

  it("skills: switching availability resets the category filter (no stale empty view)", async () => {
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Writer");
    fireEvent.click(chipBtn(/content/)); // category within usable
    fireEvent.click(chipBtn(/capabilities\.chips\.unimplemented/));
    // hollow pool has no "content" category — must not render an empty stale filter
    expect(screen.getByText("Airtable")).toBeInTheDocument();
  });

  it("assignable rows carry the equip affordance", async () => {
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Writer");
    // both usable skills expose the equip action
    expect(screen.getAllByText("capabilities.equip.action")).toHaveLength(2);
  });

  it("hides infeasible everywhere and keeps counts honest", async () => {
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Writer");
    expect(chipBtn(/capabilities\.chips\.usable/)).toHaveTextContent("2");
    expect(chipBtn(/capabilities\.chips\.unimplemented/)).toHaveTextContent("1");
    expect(chipBtn(/capabilities\.chips\.arslan_only/)).toHaveTextContent("1");
    // two "all" chips exist in skills view (availability row + category row) — take the availability one
    fireEvent.click(screen.getAllByRole("button", { name: /capabilities\.chips\.all/ })[0]);
    expect(screen.queryByText("Dead")).not.toBeInTheDocument();
  });
});
