import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createInstance, type i18n } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { companionApi, type ContextMemoryReview, type ContextReceiptRecord } from "../../api/companion";
import { companionMessages } from "../../locales/companion";
import { memoryEvidenceMessages } from "../../locales/memoryEvidence";
import appI18n from "../../i18n";
import MemoryEvidence from "./MemoryEvidence";

const row: ContextReceiptRecord = {
  id: "receipt-a", created_at: "2026-01-01T10:00:00Z",
  receipt: { id: "receipt-a", task_id: "task-a", run_id: "run:1", memory_mode: "normal",
    used: [{ id: "memory-a", kind: "memory", revision: 1 }], filter_reasons: ["irrelevant"],
    estimated_tokens: 40, cloud_use: "approved", local_only_used: false },
};
const original: ContextMemoryReview = { id: "memory-a", recorded_version: 1, current_version: 2,
  entry_status: "active", status: "available", content: "Original report rule" };
let language: i18n;
function ui(taskId = "task-a") {
  return <StrictMode><I18nextProvider i18n={language}><MemoryEvidence conversationId="conversation" taskId={taskId} /></I18nextProvider></StrictMode>;
}
async function expand() {
  fireEvent.click(screen.getByRole("button", { name: memoryEvidenceMessages.en.title }));
  await screen.findByText(memoryEvidenceMessages.en.normal);
}
beforeEach(async () => {
  language = createInstance();
  await language.use(initReactI18next).init({ lng: "en", fallbackLng: false,
    resources: Object.fromEntries(Object.entries(memoryEvidenceMessages).map(([locale, messages]) =>
      [locale, { translation: { memoryEvidence: messages, companion: companionMessages[locale as keyof typeof companionMessages] } }])),
    interpolation: { escapeValue: false },
  });
  vi.spyOn(companionApi, "contextReceipts").mockResolvedValue([row]);
  vi.spyOn(companionApi, "contextMemory").mockResolvedValue(original);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("task memory evidence", () => {
  it("keeps incomplete historical metadata readable without inventing a token count", async () => {
    vi.mocked(companionApi.contextReceipts).mockResolvedValue([{ ...row,
      receipt: { used: [null, { kind: "memory", id: "bad", revision: -1 }], filter_reasons: "legacy" },
    } as unknown as ContextReceiptRecord]);
    render(ui());
    fireEvent.click(screen.getByRole("button", { name: memoryEvidenceMessages.en.title }));
    expect(await screen.findByText(memoryEvidenceMessages.en.noneSelected)).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(memoryEvidenceMessages.en.unknown)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Memory 1/ })).not.toBeInTheDocument();
  });

  it("loads only on request, then reviews the recorded rather than current version", async () => {
    render(ui());
    expect(companionApi.contextReceipts).not.toHaveBeenCalled();
    expect(companionApi.contextMemory).not.toHaveBeenCalled();
    await expand();
    expect(companionApi.contextReceipts).toHaveBeenCalledWith("conversation", "task-a");
    expect(screen.getByText(memoryEvidenceMessages.en.explanation)).toBeInTheDocument();
    expect(screen.getByText(memoryEvidenceMessages.en.cloudApproved)).toBeInTheDocument();
    expect(screen.queryByText(original.content!)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Memory 1 · version 1" }));
    expect(await screen.findByText(original.content!)).toBeInTheDocument();
    expect(screen.getByText(memoryEvidenceMessages.en.revised)).toBeInTheDocument();
    expect(companionApi.contextMemory).toHaveBeenCalledWith("conversation", "receipt-a", "memory-a");
  });

  it("does not restore deleted text from a historical reference or cached title", async () => {
    vi.mocked(companionApi.contextReceipts).mockResolvedValue([{ ...row, receipt: { ...row.receipt,
      used: [{ ...row.receipt.used[0], ...{ title: "Cached deleted text" } }] } }]);
    vi.mocked(companionApi.contextMemory).mockResolvedValue({ ...original, status: "deleted", content: null, entry_status: "deleted" });
    render(ui()); await expand();
    expect(screen.queryByText("Cached deleted text")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Memory 1 · version 1" }));
    expect(await screen.findByText(memoryEvidenceMessages.en.deletedEntry)).toBeInTheDocument();
    expect(screen.queryByText(original.content!)).not.toBeInTheDocument();
  });

  it("distinguishes missing records from records with no selected memories", async () => {
    vi.mocked(companionApi.contextReceipts).mockResolvedValueOnce([]).mockResolvedValue([{ ...row,
      receipt: { ...row.receipt, used: [], memory_mode: "disabled", cloud_use: "not_sent" } }]);
    render(ui());
    fireEvent.click(screen.getByRole("button", { name: memoryEvidenceMessages.en.title }));
    expect(await screen.findByText(memoryEvidenceMessages.en.unrecorded)).toBeInTheDocument();
    expect(screen.queryByText(memoryEvidenceMessages.en.noneSelected)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: companionMessages.en.refresh }));
    expect(await screen.findByText(memoryEvidenceMessages.en.noneSelected)).toBeInTheDocument();
    expect(screen.getByText(memoryEvidenceMessages.en.disabled)).toBeInTheDocument();
    expect(screen.queryByText(memoryEvidenceMessages.en.unrecorded)).not.toBeInTheDocument();
  });

  it("shows a recoverable read failure without exposing server text or claiming no memory", async () => {
    vi.mocked(companionApi.contextReceipts).mockRejectedValueOnce(new Error("private internal diagnostic"));
    render(ui());
    fireEvent.click(screen.getByRole("button", { name: memoryEvidenceMessages.en.title }));
    expect(await screen.findByRole("alert")).toHaveTextContent(memoryEvidenceMessages.en.failure);
    expect(screen.queryByText("private internal diagnostic")).not.toBeInTheDocument();
    expect(screen.queryByText(memoryEvidenceMessages.en.unrecorded)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: companionMessages.en.refresh }));
    expect(await screen.findByText(memoryEvidenceMessages.en.normal)).toBeInTheDocument();
  });

  it("uses the stable receipt cursor to load older records", async () => {
    const first = Array.from({ length: 20 }, (_, index) => ({ ...row, id: `r${20 - index}`,
      receipt: { ...row.receipt, used: [] } }));
    vi.mocked(companionApi.contextReceipts).mockResolvedValueOnce(first).mockResolvedValue([{ ...row, id: "r0" }]);
    render(ui());
    fireEvent.click(screen.getByRole("button", { name: memoryEvidenceMessages.en.title }));
    fireEvent.click(await screen.findByRole("button", { name: companionMessages.en.loadMore }));
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(21));
    expect(companionApi.contextReceipts).toHaveBeenLastCalledWith("conversation", "task-a", "r1");
  });

  it("drops a late detail after refresh and reads deletion status anew", async () => {
    let resolve!: (value: ContextMemoryReview) => void;
    vi.mocked(companionApi.contextMemory).mockImplementationOnce(() => new Promise(done => { resolve = done; }))
      .mockResolvedValue({ ...original, status: "deleted", content: null });
    render(ui()); await expand();
    fireEvent.click(screen.getByRole("button", { name: "Memory 1 · version 1" }));
    fireEvent.click(screen.getByRole("button", { name: companionMessages.en.refresh }));
    await screen.findByText(memoryEvidenceMessages.en.normal);
    await act(async () => resolve(original));
    expect(screen.queryByText(original.content!)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Memory 1 · version 1" }));
    expect(await screen.findByText(memoryEvidenceMessages.en.deletedEntry)).toBeInTheDocument();
  });

  it("discards old task content and does not reuse expanded private text", async () => {
    const view = render(ui()); await expand();
    fireEvent.click(screen.getByRole("button", { name: "Memory 1 · version 1" }));
    await screen.findByText(original.content!);
    view.rerender(ui("task-b"));
    expect(screen.queryByText(original.content!)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: memoryEvidenceMessages.en.title })).toHaveAttribute("aria-expanded", "false");
    await expand();
    expect(companionApi.contextReceipts).toHaveBeenLastCalledWith("conversation", "task-b");
    expect(screen.queryByText(original.content!)).not.toBeInTheDocument();
  });

  it("renders translated states in every registered app language", async () => {
    render(ui()); await expand();
    const keys = Object.keys(memoryEvidenceMessages.en).sort();
    for (const [locale, messages] of Object.entries(memoryEvidenceMessages)) {
      expect(Object.keys(messages).sort()).toEqual(keys);
      expect(Object.values(messages).every(value => value.trim())).toBe(true);
      expect(appI18n.getResource(locale, "translation", "memoryEvidence.title")).toBe(messages.title);
      await act(async () => { await language.changeLanguage(locale); });
      expect(screen.getByRole("button", { name: messages.title })).toBeInTheDocument();
      expect(screen.getByText(messages.explanation)).toBeInTheDocument();
      expect(screen.getByText(messages.normal)).toBeInTheDocument();
      expect(screen.getByText(messages.cloudApproved)).toBeInTheDocument();
      expect(screen.getByText(new RegExp(messages.filter_irrelevant))).toBeInTheDocument();
    }
  });
});
