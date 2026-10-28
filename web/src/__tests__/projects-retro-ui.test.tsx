/** 0.1.56 P6: the retro at Done — offered, written on request; skippable. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key),
    i18n: { resolvedLanguage: "zh", language: "zh" },
  }),
}));

import RetroCard from "../components/projects/RetroCard";
import { projectsApi, type Retro } from "../api/projects";

const RETRO: Retro = {
  id: "r1", summary: "Shaping ran long.", source: "model", created_at: "",
  facts: { total_days: 40.4, plan_changes: 2, cut_checkpoints: 3,
    levels: [{ level: "Shape", band: "shaping", days: 10 }, { level: "Build", band: "doing", days: 3 }] },
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); try { localStorage.clear(); } catch { /* none */ } });

describe("the retro at Done", () => {
  it("is offered, not written, until asked; writing sends the interface language", async () => {
    vi.spyOn(projectsApi, "retro").mockResolvedValue(null);
    const write = vi.spyOn(projectsApi, "writeRetro").mockResolvedValue(RETRO);
    render(<RetroCard projectId="p1" />);
    expect(await screen.findByTestId("retro-offer")).toBeInTheDocument();
    expect(write).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("retro-write"));
    await waitFor(() => expect(write).toHaveBeenCalledWith("p1", "zh"));
    expect(await screen.findByTestId("retro-summary")).toHaveTextContent("Shaping ran long.");
    expect(screen.getByTestId("retro-facts")).toHaveTextContent('projectsUI.retroChanges:{"count":2,"cut":3}');
    expect(screen.getByTestId("retro-facts")).toHaveTextContent('projectsUI.retroTotal:{"count":40}');
  });

  it("skipping hides the offer for this project, also next time", async () => {
    vi.spyOn(projectsApi, "retro").mockResolvedValue(null);
    const { unmount } = render(<RetroCard projectId="p1" />);
    fireEvent.click(await screen.findByTestId("retro-skip"));
    expect(screen.queryByTestId("retro-offer")).toBeNull();
    unmount();
    render(<RetroCard projectId="p1" />);
    await waitFor(() => expect(projectsApi.retro).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("retro-offer")).toBeNull();
    cleanup();
    render(<RetroCard projectId="p2" />);
    expect(await screen.findByTestId("retro-offer")).toBeInTheDocument();
  });

  it("a facts-only retro (no model) shows the facts without a summary", async () => {
    vi.spyOn(projectsApi, "retro").mockResolvedValue({ ...RETRO, summary: null, source: "facts",
      facts: { ...RETRO.facts, levels: [RETRO.facts.levels[1]] } });
    render(<RetroCard projectId="p1" />);
    expect(await screen.findByTestId("retro-facts")).toHaveTextContent('projectsUI.retroChanges:{"count":2,"cut":3}');
    expect(screen.queryByTestId("retro-summary")).toBeNull();
  });
});
