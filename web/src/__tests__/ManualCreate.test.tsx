import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import "../i18n";
import { api } from "../api/client";
import Build from "../pages/Build";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({ ...(await orig<object>()), useNavigate: () => navigate, useLocation: () => ({ state: null }) }));

beforeEach(() => { navigate.mockReset(); });

describe("Manual create (NL)", () => {
  it("drafts from a description then creates and navigates to the spawn chat", async () => {
    vi.spyOn(api, "draftSpawn").mockResolvedValue({ name: "eq", domain: "finance.equity-research", capabilities: ["research"] });
    vi.spyOn(api, "createSpawn").mockResolvedValue({ id: 5, name: "eq", domain: "finance.equity-research", capabilities: ["research"], template_used: null, generation_level: 1, created_at: "", updated_at: "", persona_role: null, persona_tone: null, system_prompt: "", messages: [] } as never);
    render(<MemoryRouter><Build /></MemoryRouter>);
    // Guard: i18n resolved the keys (no raw manual_create.* key paths rendered).
    expect(screen.queryByText(/manual_create\./)).toBeNull();
    await userEvent.type(screen.getByPlaceholderText(/describe/i), "help me analyze stock fundamentals");
    await userEvent.click(screen.getByRole("button", { name: /draft/i }));
    await waitFor(() => expect(screen.getByText(/finance\.equity-research/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/chat/5"));
  });
});
