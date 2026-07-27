import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import * as imagePayload from "../lib/imagePayload";
import { useComposerAttach, AttachChips, AttachControl, type Attachment } from "../components/ComposerAttach";

// Deterministic i18n: t(key) returns the key (with crude {{n}} interpolation for chars).
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, vars?: Record<string, unknown>) =>
      vars ? `${k}:${Object.values(vars).join(",")}` : k,
  }),
}));

vi.mock("../lib/imagePayload", async (orig) => ({
  ...(await orig<typeof imagePayload>()),
  fileToImagePayload: vi.fn(),
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
      <button onClick={() => attach.addFiles([new File(["<h1>hi</h1>"], "page.html", { type: "text/html" })])}>
        add-html
      </button>
      <button onClick={() => attach.addFiles([new File(["PK"], "archive.zip", { type: "application/zip" })])}>
        add-zip
      </button>
    </div>
  );
}

describe("ComposerAttach", () => {
  it("an image is prepared for the MODEL, not sent to the extract endpoint", async () => {
    // Contract change (vision round): the model reads the picture, so there is
    // nothing to extract server-side. The old /extract round-trip only ever
    // returned "" in the packaged app — there is no OCR stack there — which is
    // exactly what made images "preview only" for every shipped build.
    vi.mocked(imagePayload.fileToImagePayload).mockResolvedValue({
      name: "shot.png", mime_type: "image/png", data: "QUJD",
    });
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByText("add-image"));
    });
    expect(m.extractAttachmentFile).not.toHaveBeenCalled();
    // The chip states where the picture is going — the disclosure the spec
    // requires at the feed entry point.
    expect(screen.getByText(/attach.image_goes_to_model/)).toBeInTheDocument();
    const last = onChange.mock.calls.at(-1)![0] as Attachment[];
    expect(last[0]).toMatchObject({
      name: "shot.png", kind: "image", text: "",
      image: { mime_type: "image/png", data: "QUJD" },
    });
  });

  it("an image that cannot be prepared says so and is NOT sent", async () => {
    // Too large after downscaling, or undecodable. Silently sending a frame the
    // socket cannot carry would look like the "Interrupted" watchdog bug.
    vi.mocked(imagePayload.fileToImagePayload).mockRejectedValue(new Error("too large"));
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByText("add-image"));
    });
    expect(screen.getByText(/attach.image_unsendable/)).toBeInTheDocument();
    const last = onChange.mock.calls.at(-1)![0] as Attachment[];
    expect(last[0]).toMatchObject({ kind: "image", ocr: "none" });
    // Discrimination: no payload means the send path contributes nothing for it.
    expect(last[0].image).toBeUndefined();
  });

  it("an .html file rides the doc extract path (backend supports it), not rejected as unsupported", async () => {
    m.extractAttachmentFile.mockResolvedValue({ text: "hi", chars: 2, truncated: false });
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByText("add-html"));
    });
    expect(m.extractAttachmentFile).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();  // no "unsupported" error
    const last = onChange.mock.calls.at(-1)![0] as Attachment[];
    expect(last[0]).toMatchObject({ name: "page.html", text: "hi", chars: 2 });
  });

  it("a genuinely unsupported type (.zip) is still rejected with an error", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByText("add-zip"));
    });
    expect(m.extractAttachmentFile).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();  // attach.unsupported
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
