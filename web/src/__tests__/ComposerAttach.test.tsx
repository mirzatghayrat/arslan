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
      <AttachControl busy={attach.busy} onPickFiles={attach.addFiles} onAddUrl={attach.addUrl} />
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

  it("URL extract goes through the SSRF-hardened api path, hidden behind the + menu", async () => {
    m.extractAttachmentUrl.mockResolvedValue({ text: "body", chars: 4, truncated: false });
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    // URL field is hidden until the toggle is clicked
    expect(screen.queryByPlaceholderText("attach.url_placeholder")).toBeNull();
    fireEvent.click(screen.getByLabelText("attach.url"));
    fireEvent.change(screen.getByPlaceholderText("attach.url_placeholder"), {
      target: { value: "https://x.com" },
    });
    fireEvent.click(screen.getByText("attach.read"));
    await waitFor(() => expect(m.extractAttachmentUrl).toHaveBeenCalledWith("https://x.com", false));
  });
});
