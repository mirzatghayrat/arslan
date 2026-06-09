import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../i18n";
import { api } from "../api/client";
import FactsPanel from "../components/settings/FactsPanel";

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listFacts").mockResolvedValue([
    { id: 1, content: "prefers metric", source: "auto", sensitive: false },
  ]);
});

describe("FactsPanel", () => {
  it("lists existing facts", async () => {
    render(<FactsPanel />);
    expect(await screen.findByDisplayValue("prefers metric")).toBeInTheDocument();
  });

  it("adds a new fact", async () => {
    const addFact = vi
      .spyOn(api, "addFact")
      .mockResolvedValue({ id: 2, content: "posts on xiaohongshu", source: "manual", sensitive: false });
    render(<FactsPanel />);
    await screen.findByDisplayValue("prefers metric");
    await userEvent.type(screen.getByPlaceholderText(/add/i), "posts on xiaohongshu");
    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    await waitFor(() => expect(addFact).toHaveBeenCalledWith({ content: "posts on xiaohongshu", sensitive: false }));
  });

  it("deletes a fact", async () => {
    const deleteFact = vi.spyOn(api, "deleteFact").mockResolvedValue(undefined);
    render(<FactsPanel />);
    await screen.findByDisplayValue("prefers metric");
    await userEvent.click(screen.getByRole("button", { name: /delete/i }));
    await waitFor(() => expect(deleteFact).toHaveBeenCalledWith(1));
  });
});
