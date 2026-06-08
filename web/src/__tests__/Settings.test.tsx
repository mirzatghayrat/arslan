import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import Settings from "../pages/Settings";
import { api } from "../api/client";

beforeEach(() => {
  vi.spyOn(api, "getSettings").mockResolvedValue({
    llm_provider: "openai",
    llm_model: "gpt-4o",
    llm_base_url: "",
    llm_api_key: "sk-...1234",
    language: "en",
  });
  vi.spyOn(api, "updateSettings").mockResolvedValue({
    llm_provider: "openai",
    llm_model: "gpt-4o",
    llm_base_url: "",
    llm_api_key: "sk-...9999",
    language: "en",
  });
});

describe("Settings", () => {
  it("loads and displays current settings", async () => {
    render(<Settings />);
    await waitFor(() => expect(api.getSettings).toHaveBeenCalled());
    expect((await screen.findByDisplayValue("gpt-4o"))).toBeInTheDocument();
  });

  it("saves settings on submit", async () => {
    render(<Settings />);
    await screen.findByDisplayValue("gpt-4o");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalled());
  });
});
