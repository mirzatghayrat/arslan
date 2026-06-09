import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import "../i18n";
import { api } from "../api/client";
import Chat from "../pages/Chat";

vi.mock("../hooks/useWebSocket", () => ({ useWebSocket: () => ({ send: vi.fn(), reconnecting: false, setLastMessageId: vi.fn() }) }));

beforeEach(() => {
  vi.spyOn(api, "getSpawn").mockResolvedValue({ id: 3, name: "GuGu", domain: "finance", capabilities: [], template_used: null, generation_level: 1, created_at: "", updated_at: "", persona_role: null, persona_tone: null, system_prompt: "", messages: [] } as never);
});

describe("Chat title", () => {
  it("shows the spawn name, not the id", async () => {
    render(<MemoryRouter initialEntries={["/chat/3"]}><Routes><Route path="/chat/:spawnId" element={<Chat />} /></Routes></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/GuGu/)).toBeInTheDocument());
  });
});
