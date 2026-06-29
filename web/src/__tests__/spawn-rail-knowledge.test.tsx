import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll } from "vitest";
import SpawnRailKnowledge from "../components/SpawnRailKnowledge";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({
  api: {
    getKnowledge: vi.fn().mockResolvedValue([{ source: "report.pdf", chunks: 4 }]),
    ingestKnowledgeText: vi.fn(), deleteKnowledge: vi.fn().mockResolvedValue(undefined),
  },
}));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

describe("SpawnRailKnowledge", () => {
  it("lists the spawn's knowledge sources", async () => {
    render(<SpawnRailKnowledge spawnId={3} />);
    await waitFor(() => expect(screen.getByText(/report.pdf/)).toBeDefined());
  });
});
