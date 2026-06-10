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

  it("renders a system spawn_created item via i18n (sentinel stripped)", () => {
    render(<ConversationBubble item={{ id: -1, kind: "system", role: "arslan", content: "__SPAWN_CREATED__:Beauty Guru" }} />);
    expect(screen.getByText(/Beauty Guru/)).toBeInTheDocument();
    expect(screen.queryByText(/__SPAWN_CREATED__/)).toBeNull();
  });

  const longContent = "# Report\n" + "data ".repeat(300); // > 800 chars

  it("renders a long finalized message as a downloadable artifact", () => {
    render(<ConversationBubble item={{ id: 11, kind: "message", role: "spawn", content: longContent, spawnName: "数据研究" }} />);
    expect(screen.getByRole("button", { name: /download/i })).toBeInTheDocument();
  });

  it("renders a short message inline (no artifact)", () => {
    render(<ConversationBubble item={{ id: 12, kind: "message", role: "arslan", content: "hi there" }} />);
    expect(screen.getByText("hi there")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download/i })).toBeNull();
  });

  it("never collapses the live streaming bubble even if long", () => {
    render(<ConversationBubble live item={{ id: -999999, kind: "message", role: "spawn", content: longContent, spawnName: "数据研究" }} />);
    expect(screen.queryByRole("button", { name: /download/i })).toBeNull();
  });
});
