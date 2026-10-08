/** 0.1.56 P6: the retro at Done — offered, written on request, rules kept; skippable. */
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
  rules: [{ text: "Time-box shaping", kept: false }, { text: "Cut early", kept: true }],
  facts: { total_days: 40.4, plan_changes: 2, cut_checkpoints: 3, slower: ["Shape"],
    levels: [{ level: "Shape", band: "shaping", days: 10, usual: 4, slower: true },
      { level: "Build", band: "doing", days: 3, usual: null, slower: false }] },
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
    expect(screen.getByTestId("retro-facts")).toHaveTextContent('projectsUI.retroSlower:{"level":"Shape","days":10,"usual":4}');
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

  it("a rule can be kept; a kept one says so", async () => {
    vi.spyOn(projectsApi, "retro").mockResolvedValue(RETRO);
    const keep = vi.spyOn(projectsApi, "keepRetroRule").mockResolvedValue({ ...RETRO,
      rules: RETRO.rules.map(r => ({ ...r, kept: true })) });
    render(<RetroCard projectId="p1" />);
    expect(await screen.findByTestId("retro-kept-1")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("retro-keep-0"));
    await waitFor(() => expect(keep).toHaveBeenCalledWith("p1", 0));
    expect(await screen.findByTestId("retro-kept-0")).toBeInTheDocument();
  });

  it("a facts-only retro (no model) shows the facts without a summary", async () => {
    vi.spyOn(projectsApi, "retro").mockResolvedValue({ ...RETRO, summary: null, source: "facts", rules: [],
      facts: { ...RETRO.facts, levels: [RETRO.facts.levels[1]], slower: [] } });
    render(<RetroCard projectId="p1" />);
    expect(await screen.findByTestId("retro-facts")).toHaveTextContent("projectsUI.retroNoneSlower");
    expect(screen.queryByTestId("retro-summary")).toBeNull();
    expect(screen.queryByTestId("retro-rules")).toBeNull();
  });
});
