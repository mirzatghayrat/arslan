import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import "../i18n";
import { api } from "../api/client";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import Conversation from "../pages/Conversation";

vi.mock("../hooks/useWebSocket", () => ({
  useWebSocket: () => ({ send: vi.fn(), reconnecting: false, setLastMessageId: vi.fn() }),
}));

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  vi.spyOn(api, "listSpawns").mockResolvedValue([]);
});

function renderPage() {
  return render(
    <MemoryRouter>
      <Conversation />
    </MemoryRouter>,
  );
}

describe("Conversation", () => {
  it("renders existing thread items from the store", async () => {
    useArslanStore.setState({
      items: [
        { id: 1, kind: "message", role: "user", content: "make me posts" },
        { id: 2, kind: "message", role: "spawn", content: "3 posts", spawnId: 7, spawnName: "Beauty Guru" },
      ],
    });
    renderPage();
    expect(screen.getByText("make me posts")).toBeInTheDocument();
    expect(screen.getByText("3 posts")).toBeInTheDocument();
    expect(screen.getAllByText(/Beauty Guru/).length).toBeGreaterThanOrEqual(1);
  });

  it("shows the streaming bubble while streaming", () => {
    useArslanStore.setState({ streaming: true, streamingText: "typing…", streamSource: "arslan" });
    renderPage();
    expect(screen.getByText("typing…")).toBeInTheDocument();
  });

  it("renders the create-spawn card when a suggestion is present", async () => {
    useArslanStore.setState({
      suggestion: { name: "beauty-guru", domain: "content-creator.xiaohongshu", capabilities: ["content-generation"] },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/beauty-guru/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /create/i })).toBeInTheDocument();
  });
});
