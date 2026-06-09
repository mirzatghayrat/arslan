import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import "../i18n";
import CreateSpawnCard from "../components/arslan/CreateSpawnCard";

const draft = {
  name: "beauty-guru",
  domain: "content-creator.xiaohongshu",
  capabilities: ["content-generation", "info-gathering"],
  persona_role: "senior skincare content creator",
  persona_tone: "data-driven",
  reason: "Recurring xiaohongshu content work",
};

function renderCard(props: Partial<React.ComponentProps<typeof CreateSpawnCard>> = {}) {
  return render(
    <MemoryRouter>
      <CreateSpawnCard draft={draft} onCreate={vi.fn()} onDismiss={vi.fn()} {...props} />
    </MemoryRouter>,
  );
}

describe("CreateSpawnCard", () => {
  it("shows the drafted spawn name and domain", () => {
    renderCard();
    expect(screen.getByText(/beauty-guru/)).toBeInTheDocument();
    expect(screen.getByText(/content-creator\.xiaohongshu/)).toBeInTheDocument();
  });

  it("calls onCreate with the draft when Create is clicked", async () => {
    const onCreate = vi.fn();
    renderCard({ onCreate });
    await userEvent.click(screen.getByRole("button", { name: /create/i }));
    expect(onCreate).toHaveBeenCalledWith(draft);
  });

  it("calls onDismiss when Dismiss is clicked", async () => {
    const onDismiss = vi.fn();
    renderCard({ onDismiss });
    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onDismiss).toHaveBeenCalled();
  });
});
