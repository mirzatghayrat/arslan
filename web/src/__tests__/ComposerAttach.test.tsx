import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useComposerAttach, AttachChips, AttachControl, type Attachment } from "../components/ComposerAttach";

// Deterministic i18n: t(key) returns the key (with crude {{n}} interpolation for chars).
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, vars?: Record<string, unknown>) =>
      vars ? `${k}:${Object.values(vars).join(",")}` : k,
  }),
}));

vi.mock("../api/client", () => ({
  api: { extractAttachmentFile: vi.fn(), extractAttachmentUrl: vi.fn() },
}));
import { api } from "../api/client";
const m = api as unknown as { extractAttachmentFile: any; extractAttachmentUrl: any };

// jsdom lacks createObjectURL
beforeEach(() => {
  vi.clearAllMocks();
  (URL as any).createObjectURL = vi.fn(() => "blob:preview");
  (URL as any).revokeObjectURL = vi.fn();
});

/** A thin harness exposing the hook's state + handlers for assertions. */
function Harness({ onChange }: { onChange: (a: Attachment[]) => void }) {
  const attach = useComposerAttach(onChange);
  return (
    <div>
      <AttachChips attachments={attach.attachments} onRemove={attach.removeAt} />
      <AttachControl busy={attach.busy} onPickFiles={attach.addFiles} />
      <input
        data-testid="composer-input"
        onChange={(e) => attach.onInputChange(e.target.value)}
        onPaste={attach.onPaste}
      />
      {attach.error && <div role="alert">{attach.error}</div>}
      <button onClick={() => attach.addFiles([new File(["x"], "shot.png", { type: "image/png" })])}>
        add-image
      </button>
    </div>
  );
}

describe("ComposerAttach", () => {
  it("image attachments OCR through the extract path and carry text into context", async () => {
    m.extractAttachmentFile.mockResolvedValue({ text: "OCR'd words", chars: 11, truncated: false });
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByText("add-image"));
    });
    expect(m.extractAttachmentFile).toHaveBeenCalledTimes(1);
    // chip reports OCR success; thumbnail stays
    expect(screen.getByText(/attach.image_ocr_ok/)).toBeInTheDocument();
    // reported attachment carries the OCR text so it rides into attached_context
    const last = onChange.mock.calls.at(-1)![0] as Attachment[];
    expect(last[0]).toMatchObject({
      name: "shot.png", kind: "image", text: "OCR'd words", chars: 11, ocr: "ok",
      previewUrl: "blob:preview",
    });
  });

  it("image with no OCR text degrades honestly to preview-only", async () => {
    m.extractAttachmentFile.mockResolvedValue({ text: "", chars: 0, truncated: false });
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByText("add-image"));
    });
    expect(screen.getByText(/attach.image_no_parse/)).toBeInTheDocument();
    const last = onChange.mock.calls.at(-1)![0] as Attachment[];
    expect(last[0]).toMatchObject({ name: "shot.png", kind: "image", text: "", chars: 0, ocr: "none" });
  });

  it("image extract failure degrades to preview-only (no error surfaced)", async () => {
    m.extractAttachmentFile.mockRejectedValue(new Error("backend down"));
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByText("add-image"));
    });
    expect(screen.getByText(/attach.image_no_parse/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    const last = onChange.mock.calls.at(-1)![0] as Attachment[];
    expect(last[0]).toMatchObject({ kind: "image", text: "", ocr: "none" });
  });

  it("auto-extracts a PASTED url immediately via the SSRF-hardened api path (no button)", async () => {
    m.extractAttachmentUrl.mockResolvedValue({ text: "body", chars: 4, truncated: false });
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    // there is no URL toggle/field anymore
    expect(screen.queryByLabelText("attach.url")).toBeNull();
    await act(async () => {
      fireEvent.paste(screen.getByTestId("composer-input"), {
        clipboardData: { files: [], getData: () => "read https://x.com now" },
      });
    });
    await waitFor(() => expect(m.extractAttachmentUrl).toHaveBeenCalledWith("https://x.com", false));
  });

  it("auto-detects a TYPED url after the debounce settles", async () => {
    vi.useFakeTimers();
    m.extractAttachmentUrl.mockResolvedValue({ text: "b", chars: 1, truncated: false });
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.change(screen.getByTestId("composer-input"), { target: { value: "see https://y.com " } });
    expect(m.extractAttachmentUrl).not.toHaveBeenCalled();   // not on keystroke
    await act(async () => { vi.advanceTimersByTime(750); });   // debounce fires
    expect(m.extractAttachmentUrl).toHaveBeenCalledWith("https://y.com", false);
    vi.useRealTimers();
  });
});
