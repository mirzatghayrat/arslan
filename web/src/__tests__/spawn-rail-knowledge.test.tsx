import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll } from "vitest";
import SpawnRailKnowledge from "../components/SpawnRailKnowledge";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({
  api: {
    getKnowledge: vi.fn().mockResolvedValue([{ source: "report.pdf", chunks: 4 }]),
    ingestKnowledgeText: vi.fn(), deleteKnowledge: vi.fn().mockResolvedValue(undefined),
    listCollections: vi.fn().mockResolvedValue([]),
    bindCollection: vi.fn().mockResolvedValue(undefined),
    unbindCollection: vi.fn().mockResolvedValue(undefined),
  },
}));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

describe("SpawnRailKnowledge", () => {
  it("lists the spawn's knowledge sources", async () => {
    render(<SpawnRailKnowledge spawnId={3} />);
    await waitFor(() => expect(screen.getByText(/report.pdf/)).toBeDefined());
  });

  it("shows bound shared collections as chips", async () => {
    const { api } = await import("../api/client");
    (api.listCollections as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: 1, name: "保险资料", chunks: 5, sources: 1, spawn_ids: [3] },
      { id: 2, name: "税务手册", chunks: 2, sources: 1, spawn_ids: [] },
    ]);
    render(<SpawnRailKnowledge spawnId={3} />);
    await waitFor(() => expect(screen.getByText(/保险资料/)).toBeDefined());
    // Unbound collection shows up in the bind select, not as a chip.
    expect(screen.getByText("税务手册")).toBeDefined();
  });
});
