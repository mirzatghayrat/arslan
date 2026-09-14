import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import BrowserReader from "../components/BrowserReader";
import { browserApi, type ReaderFrame } from "../api/browser";

const frame: ReaderFrame = { session_id: "session", conversation_id: "conversation", task_id: null, revision: 4,
  title: "Example", url: "https://example.com", text: "Untrusted <script> text", screenshot: "eA==",
  links: [{ id: "link-1", label: "Next", url: "https://example.com/next" }], can_back: true, can_forward: false,
  blocked_connections: 0, mode: "isolated_read_only" };
beforeEach(() => {
  vi.spyOn(browserApi, "createReader").mockResolvedValue({ session_id: "session" });
  vi.spyOn(browserApi, "readerAction").mockResolvedValue(frame);
  vi.spyOn(browserApi, "closeReader").mockResolvedValue(undefined);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("does not create a browser until the user navigates, and binds link clicks to the frame", async () => {
  render(<BrowserReader conversationId="conversation" taskId={null} onTitle={() => {}} />);
  expect(browserApi.createReader).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("browser.url"), { target: { value: "https://example.com" } });
  fireEvent.click(screen.getByLabelText("browser.open"));
  await screen.findByAltText("browser.screenshot");
  expect(browserApi.createReader).toHaveBeenCalledWith("conversation", null);
  fireEvent.click(screen.getByText("dock.links"));
  fireEvent.click(screen.getByText("Next"));
  await waitFor(() => expect(browserApi.readerAction).toHaveBeenLastCalledWith("session", { action: "link", link_id: "link-1", revision: 4 }));
  expect(document.querySelector("iframe")).toBeNull();
});

it("stops a live session and does not revive its old frame", async () => {
  render(<BrowserReader conversationId="conversation" taskId={null} onTitle={() => {}} />);
  fireEvent.change(screen.getByLabelText("browser.url"), { target: { value: "https://example.com" } });
  fireEvent.click(screen.getByLabelText("browser.open"));
  await screen.findByAltText("browser.screenshot");
  fireEvent.click(screen.getByLabelText("dock.stop"));
  await waitFor(() => expect(browserApi.closeReader).toHaveBeenCalledWith("session"));
  expect(screen.queryByAltText("browser.screenshot")).not.toBeInTheDocument();
});

it("closes a newly created session if the tab disappeared while creation was pending", async () => {
  let finish!: (value: { session_id: string }) => void;
  vi.mocked(browserApi.createReader).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const view = render(<BrowserReader conversationId="conversation" taskId={null} onTitle={() => {}} />);
  fireEvent.change(screen.getByLabelText("browser.url"), { target: { value: "https://example.com" } });
  fireEvent.click(screen.getByLabelText("browser.open"));
  view.unmount();
  finish({ session_id: "late" });
  await waitFor(() => expect(browserApi.closeReader).toHaveBeenCalledWith("late"));
  expect(browserApi.readerAction).not.toHaveBeenCalled();
});
