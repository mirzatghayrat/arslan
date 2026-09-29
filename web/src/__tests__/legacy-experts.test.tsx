// 0.1.44 one Arslan: former experts are turned into skills from Capabilities.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = { experts: [
  { id: 6, name: "Research Analyst", domain: "researcher", skill_key: "expert-6-research-analyst", converted: false },
  { id: 7, name: "Deck Master", domain: "content", skill_key: "expert-7-deck-master", converted: true },
] };
const request = vi.fn(async (path: string, init?: RequestInit) => {
  if (init?.method === "POST") {
    const id = Number(path.split("/")[2]);
    state.experts = state.experts.map(e => e.id === id ? { ...e, converted: true } : e);
    return { ok: true };
  }
  return { experts: state.experts };
});
vi.mock("../api/client", () => ({ request: (p: string, i?: RequestInit) => request(p, i) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) =>
  o ? `${k}:${JSON.stringify(o)}` : k }) }));
import LegacyExperts from "../components/companion/LegacyExperts";

afterEach(() => { cleanup(); request.mockClear(); });

describe("former experts", () => {
  it("lists them, converts one on click, and shows it saved", async () => {
    render(<LegacyExperts />);
    expect(await screen.findByText("Research Analyst")).toBeInTheDocument();
    expect(screen.getByTestId("converted-7")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("to-skill-6"));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/experts/6/to-skill", { method: "POST" }));
    expect(await screen.findByTestId("converted-6")).toBeInTheDocument();
  });
});
