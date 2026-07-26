/**
 * Composer drafts must survive unmount (v0.1.0 field report: type a long
 * prompt, hop to Settings to fix the API key, come back — text gone).
 */
import { describe, it, expect, vi } from "vitest";
import { render, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OrchestratorChat from "../components/OrchestratorChat";

const base = {
  chatHistory: [],
  setChatHistory: vi.fn(),
  spawns: [],
  onSendMessage: vi.fn(),
  currentStyle: "quartz" as const,
  setCurrentStyle: vi.fn(),
  activeThread: null,
};

describe("composer draft survives unmount", () => {
  it("restores typed text after unmount/remount of the same conversation", async () => {
    const u = userEvent.setup();
    const first = render(<OrchestratorChat {...base} conversationId="draft-conv" />);
    const box = first.container.querySelector("textarea")!;
    await u.type(box, "half-written prompt");
    expect((box as HTMLTextAreaElement).value).toBe("half-written prompt");

    cleanup(); // navigate away — component unmounts

    const second = render(<OrchestratorChat {...base} conversationId="draft-conv" />);
    const box2 = second.container.querySelector("textarea")! as HTMLTextAreaElement;
    expect(box2.value).toBe("half-written prompt");
  });

  it("keeps drafts per conversation (control: no cross-talk)", async () => {
    const u = userEvent.setup();
    const a = render(<OrchestratorChat {...base} conversationId="conv-a" />);
    await u.type(a.container.querySelector("textarea")!, "for A only");
    cleanup();
    const b = render(<OrchestratorChat {...base} conversationId="conv-b" />);
    expect((b.container.querySelector("textarea") as HTMLTextAreaElement).value).toBe("");
  });
});
