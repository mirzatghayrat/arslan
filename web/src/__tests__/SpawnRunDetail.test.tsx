import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({ api: { getRuns: vi.fn().mockResolvedValue([
  { id: 7, spawn_name: "Bad", status: "scored", overall_score: 5.2, total_ms: 31400, user_message: "do it", created_at: "2026-07-07T10:00:00" },
]) } }));
import SpawnRunDetail from "../components/SpawnRunDetail";

describe("SpawnRunDetail", () => {
  it("lists the spawn's runs and selects one", async () => {
    const onSel = vi.fn();
    render(<SpawnRunDetail spawnId={1} spawnName="Bad" onBack={() => {}} onSelectRun={onSel} />);
    const row = await screen.findByText(/do it/);
    fireEvent.click(row.closest("[data-testid='run-row']")!);
    await waitFor(() => expect(onSel).toHaveBeenCalledWith(7));
  });
  it("back button calls onBack", async () => {
    const onBack = vi.fn();
    render(<SpawnRunDetail spawnId={1} spawnName="Bad" onBack={onBack} onSelectRun={() => {}} />);
    await screen.findByText(/do it/);
    fireEvent.click(screen.getByText(/Diagnostics/));
    expect(onBack).toHaveBeenCalled();
  });
});
