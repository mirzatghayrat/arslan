import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

it("retains a failed-to-close session for an explicit stop retry", async () => {
  render(<BrowserReader conversationId="conversation" taskId={null} onTitle={() => {}} />);
  fireEvent.change(screen.getByLabelText("browser.url"), { target: { value: "https://example.com" } });
  fireEvent.click(screen.getByLabelText("browser.open"));
  await screen.findByAltText("browser.screenshot");
  vi.mocked(browserApi.closeReader).mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(screen.getByLabelText("dock.stop"));
  await screen.findByRole("alert");
  expect(screen.queryByAltText("browser.screenshot")).not.toBeInTheDocument();
  expect(screen.getByLabelText("dock.stop")).toBeEnabled();
  fireEvent.click(screen.getByLabelText("dock.stop"));
  await waitFor(() => expect(browserApi.closeReader).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByLabelText("dock.stop")).toBeDisabled());
  expect(browserApi.closeReader).toHaveBeenLastCalledWith("session");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("does not start another navigation while the previous session is closing", async () => {
  render(<BrowserReader conversationId="conversation" taskId={null} onTitle={() => {}} />);
  fireEvent.change(screen.getByLabelText("browser.url"), { target: { value: "https://example.com" } });
  fireEvent.click(screen.getByLabelText("browser.open"));
  await screen.findByAltText("browser.screenshot");
  let finish!: () => void;
  vi.mocked(browserApi.closeReader).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByLabelText("dock.stop"));
  expect(screen.getByLabelText("browser.open")).toBeDisabled();
  expect(screen.getByLabelText("dock.stop")).toBeDisabled();
  fireEvent.submit(screen.getByLabelText("browser.url").closest("form")!);
  expect(browserApi.createReader).toHaveBeenCalledTimes(1);
  expect(browserApi.readerAction).toHaveBeenCalledTimes(1);
  await act(async () => finish());
  expect(screen.getByLabelText("browser.open")).toBeEnabled();
  fireEvent.click(screen.getByLabelText("browser.open"));
  await screen.findByAltText("browser.screenshot");
  expect(browserApi.createReader).toHaveBeenCalledTimes(2);
});

it("retries cleanup on unmount after a failed explicit stop", async () => {
  const view = render(<BrowserReader conversationId="conversation" taskId={null} onTitle={() => {}} />);
  fireEvent.change(screen.getByLabelText("browser.url"), { target: { value: "https://example.com" } });
  fireEvent.click(screen.getByLabelText("browser.open"));
  await screen.findByAltText("browser.screenshot");
  vi.mocked(browserApi.closeReader).mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(screen.getByLabelText("dock.stop"));
  await screen.findByRole("alert");
  view.unmount();
  expect(browserApi.closeReader).toHaveBeenCalledTimes(2);
  expect(browserApi.closeReader).toHaveBeenLastCalledWith("session");
});

it("does not publish an in-flight frame after a failed stop", async () => {
  const onTitle = vi.fn();
  render(<BrowserReader conversationId="conversation" taskId={null} onTitle={onTitle} />);
  fireEvent.change(screen.getByLabelText("browser.url"), { target: { value: "https://example.com" } });
  fireEvent.click(screen.getByLabelText("browser.open"));
  await screen.findByAltText("browser.screenshot");
  let finish!: (value: ReaderFrame) => void;
  vi.mocked(browserApi.readerAction).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByLabelText("dock.refresh"));
  vi.mocked(browserApi.closeReader).mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(screen.getByLabelText("dock.stop"));
  await screen.findByRole("alert");
  await act(async () => finish({ ...frame, title: "Late frame", revision: 5 }));
  expect(screen.queryByAltText("browser.screenshot")).not.toBeInTheDocument();
  expect(onTitle).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("dock.stop")).toBeEnabled();
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

it.each(["browser.navigation_failed", "browser.frame_too_large", "browser.stale_view", "browser.runtime_failed", "browser.session_expired"])(
  "removes the previous screenshot and link controls after %s", async code => {
    render(<BrowserReader conversationId="conversation" taskId={null} onTitle={() => {}} />);
    fireEvent.change(screen.getByLabelText("browser.url"), { target: { value: "https://example.com" } });
    fireEvent.click(screen.getByLabelText("browser.open"));
    await screen.findByAltText("browser.screenshot");
    vi.mocked(browserApi.readerAction).mockRejectedValueOnce({ detail: { code } });
    fireEvent.click(screen.getByLabelText("dock.refresh"));
    await screen.findByRole("alert");
    expect(screen.queryByAltText("browser.screenshot")).not.toBeInTheDocument();
    expect(screen.queryByText("Next")).not.toBeInTheDocument();
    expect(screen.getByLabelText("dock.refresh")).toBeDisabled();
    if (!["browser.runtime_failed", "browser.session_expired"].includes(code)) {
      expect(screen.getByLabelText("dock.stop")).not.toBeDisabled();
    }
    fireEvent.click(screen.getByLabelText("browser.open"));
    await screen.findByAltText("browser.screenshot");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(browserApi.createReader).toHaveBeenCalledTimes(
      ["browser.runtime_failed", "browser.session_expired"].includes(code) ? 2 : 1,
    );
  });
