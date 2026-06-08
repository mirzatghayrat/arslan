import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import SpawnCard from "../components/spawn/SpawnCard";
import type { SpawnSummary } from "../types";

const spawn: SpawnSummary = {
  id: 3,
  name: "beauty-guru",
  domain: "content-creator.xiaohongshu",
  capabilities: ["content-generation"],
  template_used: null,
  generation_level: 1,
  created_at: "",
  updated_at: "",
};

describe("SpawnCard", () => {
  it("renders the spawn name and domain", () => {
    render(
      <MemoryRouter>
        <SpawnCard spawn={spawn} onDelete={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByText("beauty-guru")).toBeInTheDocument();
    expect(screen.getByText(/content-creator/)).toBeInTheDocument();
  });

  it("calls onDelete when the delete button is clicked", async () => {
    const onDelete = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <MemoryRouter>
        <SpawnCard spawn={spawn} onDelete={onDelete} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /delete/i }));
    expect(onDelete).toHaveBeenCalledWith(3);
  });
});
