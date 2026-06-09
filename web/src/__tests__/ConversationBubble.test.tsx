import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "../i18n";
import ConversationBubble from "../components/arslan/ConversationBubble";

describe("ConversationBubble", () => {
  it("renders a user message right-aligned", () => {
    render(<ConversationBubble item={{ id: 1, kind: "message", role: "user", content: "hi there" }} />);
    expect(screen.getByText("hi there")).toBeInTheDocument();
  });

  it("renders a spawn message named, with a routed-to caption", () => {
    render(
      <ConversationBubble
        item={{ id: 2, kind: "message", role: "spawn", content: "3 posts", spawnId: 7, spawnName: "Beauty Guru" }}
      />,
    );
    expect(screen.getByText("3 posts")).toBeInTheDocument();
    // Name appears in both the faint caption and the bold in-bubble header.
    expect(screen.getAllByText(/Beauty Guru/).length).toBeGreaterThanOrEqual(2);
  });

  it("uses purple tone for spawn bubbles", () => {
    const { container } = render(
      <ConversationBubble
        item={{ id: 3, kind: "message", role: "spawn", content: "x", spawnId: 7, spawnName: "Guru" }}
      />,
    );
    expect(container.querySelector(".bg-purple-500\\/15")).not.toBeNull();
  });

  it("renders a fact item as a remember chip", () => {
    render(
      <ConversationBubble item={{ id: -1, kind: "fact", role: "arslan", content: "posts on xiaohongshu" }} />,
    );
    expect(screen.getByText(/posts on xiaohongshu/)).toBeInTheDocument();
  });
});
