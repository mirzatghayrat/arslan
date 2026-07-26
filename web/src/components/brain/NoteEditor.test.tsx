import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({
  api: {
    getNote: vi.fn().mockResolvedValue({
      id: 1,
      title: "OKX 模板",
      content: "参见材料库",
      tags: ["deck"],
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-02T00:00:00",
      backlinks: [{ id: 2, title: "来源笔记" }],
    }),
    updateNote: vi.fn().mockResolvedValue({
      id: 1,
      title: "OKX 模板",
      content: "参见材料库",
      tags: ["deck"],
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-02T00:00:00",
    }),
    deleteNote: vi.fn().mockResolvedValue({ deleted: true }),
    suggestNoteLinks: vi.fn().mockResolvedValue({
      suggestions: [{ target: "材料库", kind: "material", reason: "同讲 OKX" }],
      tags: ["okx", "deck"],
    }),
  },
}));

import NoteEditor from "./NoteEditor";

describe("NoteEditor", () => {
  it("loads and renders the note title + backlinks", async () => {
    render(<NoteEditor noteId={1} onClose={() => {}} onChanged={() => {}} allLabels={["材料库"]} />);
    await waitFor(() => expect(screen.getByDisplayValue("OKX 模板")).toBeInTheDocument());
    expect(screen.getByText("来源笔记")).toBeInTheDocument();
  });

  it("shows a [[ autocomplete dropdown filtered from allLabels", async () => {
    render(<NoteEditor noteId={1} onClose={() => {}} onChanged={() => {}} allLabels={["材料库", "别的笔记"]} />);
    const textarea = await screen.findByDisplayValue("参见材料库");
    fireEvent.change(textarea, { target: { value: "参见材料库 [[材" } });
    (textarea as HTMLTextAreaElement).setSelectionRange(
      "参见材料库 [[材".length,
      "参见材料库 [[材".length,
    );
    fireEvent.select(textarea);
    await waitFor(() => expect(screen.getByText("材料库")).toBeInTheDocument());
  });

  it("clicking AI 建议关联 lists a suggestion", async () => {
    render(<NoteEditor noteId={1} onClose={() => {}} onChanged={() => {}} allLabels={[]} />);
    await waitFor(() => expect(screen.getByDisplayValue("OKX 模板")).toBeInTheDocument());
    fireEvent.click(screen.getByText("brain.ai_suggest"));
    await waitFor(() => expect(screen.getByText(/同讲 OKX/)).toBeInTheDocument());
    expect(screen.getByText("材料库", { selector: ".note-editor__sugg-target" })).toBeInTheDocument();
  });

  it("保存 calls updateNote with edited fields", async () => {
    const onChanged = vi.fn();
    const { api } = await import("../../api/client");
    render(<NoteEditor noteId={1} onClose={() => {}} onChanged={onChanged} allLabels={[]} />);
    const title = await screen.findByDisplayValue("OKX 模板");
    fireEvent.change(title, { target: { value: "OKX 模板 v2" } });
    fireEvent.click(screen.getByText("brain.save"));
    await waitFor(() => expect(api.updateNote).toHaveBeenCalledWith(1, expect.objectContaining({ title: "OKX 模板 v2" })));
    expect(onChanged).toHaveBeenCalled();
  });

  it("删除 calls deleteNote then onChanged + onClose", async () => {
    const onChanged = vi.fn();
    const onClose = vi.fn();
    const { api } = await import("../../api/client");
    render(<NoteEditor noteId={1} onClose={onClose} onChanged={onChanged} allLabels={[]} />);
    await waitFor(() => expect(screen.getByDisplayValue("OKX 模板")).toBeInTheDocument());
    fireEvent.click(screen.getByText("brain.delete"));
    await waitFor(() => expect(api.deleteNote).toHaveBeenCalledWith(1));
    expect(onChanged).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
