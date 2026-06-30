import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SpawnStudio from "../components/SpawnStudio";

vi.mock("../api/client", () => ({
  api: {
    getRegistry: vi.fn(),
    getSpawn: vi.fn(),
    getSeeds: vi.fn(),
    updateEquipment: vi.fn(),
    createSpawn: vi.fn(),
    deleteSpawn: vi.fn(),
    draftSpawn: vi.fn(),
  },
}));
import { api } from "../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const REGISTRY = {
  toolsets: [
    { key: "web_search", name: "Web Search", description: "search the web", tier: "tier-1", status: "ok", assignable: true, tools: [] },
    { key: "mcp_5", name: "Notion MCP", description: "notion server", tier: "tier-2", status: "ok", assignable: true, tools: [] },
    { key: "locked_tool", name: "Locked", description: "no", tier: "tier-3", status: "ok", assignable: false, tools: [] },
  ],
  skills: [
    { key: "seo-opt", name: "SEO", category: "writing", description: "seo skill", tier: "tier-1", status: "ok", assignable: true },
  ],
};

const SPAWN_DETAIL = {
  id: 7,
  name: "小美",
  domain: "marketing",
  capabilities: [],
  template_used: null,
  generation_level: 1,
  created_at: "",
  updated_at: "",
  persona_role: "Own the brand voice",
  persona_tone: null,
  system_prompt: "",
  messages: [],
  equipment: { toolsets: [{ key: "web_search", name: "Web Search", status: "ok", grant: "permanent" }], skills: [] },
  seeds: [{ slug: "copywriter", name: "Copywriter", division: "Creative", summary: "writes" }],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.getRegistry.mockResolvedValue(REGISTRY);
  m.getSpawn.mockResolvedValue(SPAWN_DETAIL);
  m.getSeeds.mockResolvedValue({ seeds: [{ slug: "researcher", name: "Researcher", division: "Analysis", summary: "digs" }], total: 1 });
});

describe("SpawnStudio — edit mode", () => {
  it("renders details, composed seeds, three panels with pre-checked equipment", async () => {
    render(<SpawnStudio mode="edit" spawnId={7} onClose={() => {}} />);
    await screen.findByTestId("spawn-studio-panel-skill");
    expect(screen.getByTestId("spawn-studio-panel-tool")).toBeTruthy();
    expect(screen.getByTestId("spawn-studio-panel-mcp")).toBeTruthy();
    // composed seed chip
    expect(screen.getByTestId("spawn-studio-composed-seeds").textContent).toContain("Copywriter");
    // equipped web_search pre-selected
    await waitFor(() =>
      expect(screen.getByTestId("spawn-studio-item-web_search").getAttribute("aria-pressed")).toBe("true"),
    );
    // locked tool disabled
    expect((screen.getByTestId("spawn-studio-item-locked_tool") as HTMLButtonElement).disabled).toBe(true);
  });

  it("toggles a skill + MCP and saves merged toolsets+skills", async () => {
    m.updateEquipment.mockResolvedValue({});
    const onSaved = vi.fn();
    render(<SpawnStudio mode="edit" spawnId={7} onClose={() => {}} onSaved={onSaved} />);
    fireEvent.click(await screen.findByTestId("spawn-studio-item-seo-opt"));
    fireEvent.click(screen.getByTestId("spawn-studio-item-mcp_5"));
    fireEvent.click(screen.getByTestId("spawn-studio-save"));
    await waitFor(() => expect(m.updateEquipment).toHaveBeenCalledTimes(1));
    const [id, body] = m.updateEquipment.mock.calls[0];
    expect(id).toBe(7);
    expect(new Set(body.toolsets)).toEqual(new Set(["web_search", "mcp_5"]));
    expect(body.skills).toEqual(["seo-opt"]);
    expect(onSaved).toHaveBeenCalled();
  });

  it("deletes after confirm", async () => {
    m.deleteSpawn.mockResolvedValue(undefined);
    const onClose = vi.fn();
    const onSaved = vi.fn();
    render(<SpawnStudio mode="edit" spawnId={7} onClose={onClose} onSaved={onSaved} />);
    fireEvent.click(await screen.findByTestId("spawn-studio-delete"));
    fireEvent.click(await screen.findByTestId("spawn-studio-delete-yes"));
    await waitFor(() => expect(m.deleteSpawn).toHaveBeenCalledWith(7));
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});

describe("SpawnStudio — create mode", () => {
  it("recommend pre-fills name/domain and pre-selects panels + seeds", async () => {
    m.draftSpawn.mockResolvedValue({
      name: "GrowthBot",
      domain: "growth",
      capabilities: ["seo"],
      persona_role: "Drive growth",
      tools: ["web_search"],
      skills: ["seo-opt"],
      mcps: ["mcp_5"],
      seed_refs: ["researcher"],
    });
    render(<SpawnStudio mode="create" onClose={() => {}} />);
    await screen.findByTestId("spawn-studio-recommend");
    fireEvent.change(screen.getByTestId("spawn-studio-scope"), { target: { value: "help us grow" } });
    fireEvent.click(screen.getByTestId("spawn-studio-recommend-btn"));
    await waitFor(() =>
      expect((screen.getByTestId("spawn-studio-name") as HTMLInputElement).value).toBe("GrowthBot"),
    );
    expect((screen.getByTestId("spawn-studio-domain") as HTMLInputElement).value).toBe("growth");
    await waitFor(() =>
      expect(screen.getByTestId("spawn-studio-item-web_search").getAttribute("aria-pressed")).toBe("true"),
    );
    expect(screen.getByTestId("spawn-studio-item-mcp_5").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("spawn-studio-item-seo-opt").getAttribute("aria-pressed")).toBe("true");
    // seed pre-selected
    await waitFor(() =>
      expect(screen.getByTestId("spawn-studio-seed-researcher").getAttribute("aria-pressed")).toBe("true"),
    );
  });

  it("create sends seed_refs + equipment; disabled until a name exists", async () => {
    m.createSpawn.mockResolvedValue({});
    const onSaved = vi.fn();
    render(<SpawnStudio mode="create" onClose={() => {}} onSaved={onSaved} />);
    const createBtn = await screen.findByTestId("spawn-studio-create");
    expect((createBtn as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId("spawn-studio-name"), { target: { value: "Newbie" } });
    fireEvent.change(screen.getByTestId("spawn-studio-domain"), { target: { value: "ops" } });
    // pick a seed + a skill
    fireEvent.click(await screen.findByTestId("spawn-studio-seed-researcher"));
    fireEvent.click(screen.getByTestId("spawn-studio-item-seo-opt"));
    fireEvent.click(screen.getByTestId("spawn-studio-create"));
    await waitFor(() => expect(m.createSpawn).toHaveBeenCalledTimes(1));
    const body = m.createSpawn.mock.calls[0][0];
    expect(body.name).toBe("Newbie");
    expect(body.domain).toBe("ops");
    expect(body.seed_refs).toEqual(["researcher"]);
    expect(body.equipment.skills).toEqual(["seo-opt"]);
    expect(onSaved).toHaveBeenCalled();
  });
});
