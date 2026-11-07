/** 0.1.52 S3: links to earlier conversations open them in the app, never a new window. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

import MarkdownLink from "../components/MarkdownLink";
import { conversationFromLink, conversationToOpen, OPEN_CONVERSATION_EVENT } from "../lib/openConversation";

afterEach(() => cleanup());

describe("conversation links", () => {
  it("parses only the in-app form", () => {
    expect(conversationFromLink("#conversation=thread-abc")).toBe("thread-abc");
    expect(conversationFromLink("#conversation=thread%20x")).toBe("thread x");
    expect(conversationFromLink("https://example.com/#conversation=x")).toBeNull();
    expect(conversationFromLink("#conversation=")).toBeNull();
    expect(conversationFromLink(undefined)).toBeNull();
  });

  it("a click asks the app to open the conversation instead of navigating", () => {
    const seen = vi.fn();
    window.addEventListener(OPEN_CONVERSATION_EVENT, (e) => seen((e as CustomEvent).detail));
    render(<MarkdownLink href="#conversation=thread-1">last week</MarkdownLink>);
    const link = screen.getByText("last week");
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    fireEvent(link, click);
    expect(click.defaultPrevented).toBe(true);
    expect(seen).toHaveBeenCalledWith("thread-1");
  });

  it("the app opens only a conversation the user has", () => {
    const threads = [{ id: "thread-1" }, { id: "old", archived: true }];
    expect(conversationToOpen("thread-1", threads)).toBe("thread-1");
    expect(conversationToOpen("old", threads)).toBeNull();
    expect(conversationToOpen("someone-elses", threads)).toBeNull();
  });
});
