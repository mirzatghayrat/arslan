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
  it("image attachments degrade honestly (preview-only, no text in context)", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByText("add-image"));
    });
    // honest label
    expect(screen.getByText(/attach.image_no_parse/)).toBeInTheDocument();
    // reported attachment carries empty text so it never injects into context
    const last = onChange.mock.calls.at(-1)![0] as Attachment[];
    expect(last[0]).toMatchObject({ name: "shot.png", kind: "image", text: "", chars: 0 });
    // file-extract path is NOT used for images
    expect(m.extractAttachmentFile).not.toHaveBeenCalled();
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
