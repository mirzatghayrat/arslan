import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import "../i18n";
import { api } from "../api/client";
import App from "../App";

vi.mock("../hooks/useWebSocket", () => ({
  useWebSocket: () => ({ send: vi.fn(), reconnecting: false, setLastMessageId: vi.fn() }),
}));

beforeEach(() => {
  vi.spyOn(api, "listSpawns").mockResolvedValue([]);
});

describe("routing", () => {
  it("renders the Conversation page at /", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByPlaceholderText(/message arslan/i)).toBeInTheDocument();
  });

  it("renders the Dashboard (spawn roster) at /spawns", () => {
    render(
      <MemoryRouter initialEntries={["/spawns"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText(/your spawns/i)).toBeInTheDocument();
  });
});
