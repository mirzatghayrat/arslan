import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EquipPopover from "../components/EquipPopover";

// i18n passthrough
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("../api/client", () => ({ api: { listSpawns: vi.fn(), updateEquipment: vi.fn() } }));
import { api } from "../api/client";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const perm = (key: string, granted_by: "create" | "user" = "user") => ({
  key, name: key, status: "registered", grant: "permanent" as const, granted_by,
});
const temp = (key: string) => ({
  key, name: key, status: "registered", grant: "temporary" as const, granted_by: "escalation" as const,
});

const SPAWNS = [
  {
    id: 1, name: "Mermer", domain: "d", capabilities: [], template_used: null,
    generation_level: 0, created_at: "", updated_at: "",
    equipment: { toolsets: [perm("web_search_scraping", "create")], skills: [perm("writer")] },
  },
  {
    id: 2, name: "Kanat", domain: "d", capabilities: [], template_used: null,
    generation_level: 0, created_at: "", updated_at: "",
    equipment: { toolsets: [perm("charting", "create")], skills: [perm("plan"), temp("spike")] },
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  m.listSpawns.mockResolvedValue(structuredClone(SPAWNS));
  m.updateEquipment.mockResolvedValue({ id: 2, equipment: null });
});

const open = async () => {
  fireEvent.click(screen.getByRole("button", { name: "capabilities.equip.action" }));
  await screen.findByText("Mermer");
};

describe("EquipPopover", () => {
  it("opens a popover listing spawns with checkboxes reflecting current equipment", async () => {
    render(<EquipPopover kind="skill" capKey="writer" />);
    await open();
    expect(screen.getByText("Kanat")).toBeInTheDocument();
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes[0].checked).toBe(true);  // Mermer has writer
    expect(boxes[1].checked).toBe(false); // Kanat doesn't
  });

  it("equipping merges the key into the spawn's list and sends BOTH lists (toolsets preserved)", async () => {
    render(<EquipPopover kind="skill" capKey="writer" />);
    await open();
    const kanat = screen.getAllByRole("checkbox")[1];
    fireEvent.click(kanat);
    await waitFor(() => expect(m.updateEquipment).toHaveBeenCalledTimes(1));
    // Kanat: toolsets kept as-is; skills = existing user-managed + writer.
    // The temporary "spike" grant must NOT be sent (replace would promote it).
    expect(m.updateEquipment).toHaveBeenCalledWith(2, {
      toolsets: ["charting"],
      skills: ["plan", "writer"],
    });
  });

  it("unequipping removes only this key and keeps the other list intact", async () => {
    render(<EquipPopover kind="skill" capKey="writer" />);
    await open();
    const mermer = screen.getAllByRole("checkbox")[0];
    fireEvent.click(mermer);
    await waitFor(() => expect(m.updateEquipment).toHaveBeenCalledTimes(1));
    expect(m.updateEquipment).toHaveBeenCalledWith(1, {
      toolsets: ["web_search_scraping"],
      skills: [],
    });
  });

  it("toolset kind mutates the toolsets list and preserves skills", async () => {
    render(<EquipPopover kind="toolset" capKey="deck" />);
    await open();
    fireEvent.click(screen.getAllByRole("checkbox")[1]); // Kanat
    await waitFor(() => expect(m.updateEquipment).toHaveBeenCalledTimes(1));
    expect(m.updateEquipment).toHaveBeenCalledWith(2, {
      toolsets: ["charting", "deck"],
      skills: ["plan"],
    });
  });

  it("optimistically checks the box, then rolls back with honest error text on failure", async () => {
    m.updateEquipment.mockRejectedValue(new Error("boom"));
    render(<EquipPopover kind="skill" capKey="writer" />);
    await open();
    const kanat = () => (screen.getAllByRole("checkbox") as HTMLInputElement[])[1];
    expect(kanat().checked).toBe(false);
    fireEvent.click(kanat());
    // rollback: unchecked again + honest failure text shown
    await screen.findByText("capabilities.equip.error");
    expect(kanat().checked).toBe(false);
    // the other spawn's state was untouched
    expect((screen.getAllByRole("checkbox") as HTMLInputElement[])[0].checked).toBe(true);
  });

  it("shows an honest empty state when there are no spawns", async () => {
    m.listSpawns.mockResolvedValue([]);
    render(<EquipPopover kind="skill" capKey="writer" />);
    fireEvent.click(screen.getByRole("button", { name: "capabilities.equip.action" }));
    expect(await screen.findByText("capabilities.equip.empty")).toBeInTheDocument();
  });
});
