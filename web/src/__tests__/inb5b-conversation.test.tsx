/** INB5b (v0.1.64): what waited in the Inbox comes back to its conversation (the INB5 board, approved 2026-10-31). What wasn't done
 *  while you were away sits on top of the conversation; a stopped job's card sits in it with 「接着做」/「先放着」/「不用了」, and a card set
 *  aside or handled stays on its row with its state (Q7). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, params?: object) => (params ? `${key}:${JSON.stringify(params)}` : key),
    i18n: { language: "en", resolvedLanguage: "en" } }),
}));
vi.mock("../api/client", () => {
  class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
  return { ApiError, request: vi.fn(), api: {} };
});
vi.mock("../api/proactive", () => ({
  PROACTIVE_CHANGED: "arslan:proactive-changed",
  announceProactiveChange: () => {},
  proactiveApi: { items: vi.fn(), accept: vi.fn(), snooze: vi.fn(), dismiss: vi.fn() },
}));

import { ApiError, request } from "../api/client";
import { proactiveApi } from "../api/proactive";
import { AwayEntries, StoppedJobCards } from "../components/conversation/WhileAway";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const away = (id: number, unattended: boolean, conversation_id = "c1") => ({
  id, created_at: "2026-10-31T08:00:00Z", first_at: "2026-10-31T07:00:00Z", count: 2, conversation_id, kind: "send",
  target: `mail:team-${id}`, detail: `send mail ${id}`, always_ok: false, always: [], unattended,
});
const followup = (id: number, status = "new", over: Record<string, unknown> = {}) => ({
  id, kind: "job_followup", title_key: "title.job_followup", params: {}, evidence: [], goal: "g", priority: "normal", status,
  diagnosis: null, conversation_id: "c1", job_id: "j1", created_at: "2026-10-31T08:00:00Z", snooze_until: null,
  source_key: `job:${id}`, ...over,
});

describe("what wasn't done while you were away", () => {
  it("sits on top of its own conversation, without a scheduled run's entries", async () => {
    vi.mocked(request).mockResolvedValue([away(1, false), away(2, true)] as never);
    render(<AwayEntries conversationId="c1" />);
    const list = await screen.findByTestId("inbox-refused");
    expect(list).toHaveAttribute("aria-label", "whileAway.title");
    expect(within(list).getAllByTestId("inbox-refused-row")).toHaveLength(1);       // the scheduled run's entry is its task's
    const asked = String(vi.mocked(request).mock.calls[0][0]);
    expect(asked).toContain("conversation_id=c1");
    expect(asked).toContain("hours=24");
  });

  it("shows nothing when nothing waits", async () => {
    vi.mocked(request).mockResolvedValue([] as never);
    const { container } = render(<AwayEntries conversationId="c1" />);
    await waitFor(() => expect(request).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("a stopped job's card", () => {
  it("sits in its conversation with 「接着做」, 「先放着」 and 「不用了」, and 「接着做」 carries on there", async () => {
    vi.mocked(proactiveApi.items).mockResolvedValue({ items: [followup(5)] } as never);
    vi.mocked(proactiveApi.accept).mockResolvedValue({ conversation_id: "c1" } as never);
    const onOpenConversation = vi.fn();
    render(<StoppedJobCards conversationId="c1" onOpenConversation={onOpenConversation} />);
    const card = await screen.findByTestId("proactive-item-5");
    expect(proactiveApi.items).toHaveBeenCalledWith("all", { conversationId: "c1", kind: "job_followup" });
    expect(within(card).getByText("proactive.item.snooze")).toBeInTheDocument();
    expect(within(card).getByText("proactive.item.notUseful")).toBeInTheDocument();
    fireEvent.click(within(card).getByText("proactive.item.doIt"));
    await waitFor(() => expect(proactiveApi.accept).toHaveBeenCalledWith(5, undefined));   // its own conversation, not a new one
    expect(onOpenConversation).toHaveBeenCalledWith("c1", false);
  });

  it("keeps a card set aside or handled on its row with its state (Q7)", async () => {
    vi.mocked(proactiveApi.items).mockResolvedValue({ items: [
      followup(6, "dismissed"), followup(5, "snoozed", { snooze_until: "2026-11-03T08:00:00Z" })] } as never);   // newest first, as the server lists
    render(<StoppedJobCards conversationId="c1" onOpenConversation={vi.fn()} />);
    const older = await screen.findByTestId("proactive-item-5");
    const newer = screen.getByTestId("proactive-item-6");
    expect(within(older).getByText(/proactive\.item\.snoozedUntil/)).toBeInTheDocument();
    expect(within(newer).getByText("proactive.item.dismissed")).toBeInTheDocument();
    expect(older.compareDocumentPosition(newer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();   // oldest first, as the conversation reads
  });

  it("without a model, 「接着做」 says so and offers the model settings", async () => {
    vi.mocked(proactiveApi.items).mockResolvedValue({ items: [followup(5)] } as never);
    vi.mocked(proactiveApi.accept).mockRejectedValue(new ApiError("no_model", 400));
    const onOpenModelSettings = vi.fn();
    render(<StoppedJobCards conversationId="c1" onOpenConversation={vi.fn()} onOpenModelSettings={onOpenModelSettings} />);
    fireEvent.click(within(await screen.findByTestId("proactive-item-5")).getByText("proactive.item.doIt"));
    fireEvent.click(await screen.findByText("proactive.item.errors.openModels"));
    expect(onOpenModelSettings).toHaveBeenCalled();
  });

  it("shows nothing for a conversation with no stopped job", async () => {
    vi.mocked(proactiveApi.items).mockResolvedValue({ items: [] } as never);
    const { container } = render(<StoppedJobCards conversationId="c1" onOpenConversation={vi.fn()} />);
    await waitFor(() => expect(proactiveApi.items).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
