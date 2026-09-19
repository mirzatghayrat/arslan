import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ArtifactPreview from "../components/ArtifactPreview";
import { api } from "../api/client";
import type { StoredArtifact } from "../api/client.types";

const file: StoredArtifact = { kind: "file", run_id: 7, filename: "sample.mp4", title: "sample",
  bytes: 3, sha256: "00".repeat(32), media_type: "video/mp4", url: "https://never-follow.example" };
beforeEach(() => {
  vi.spyOn(api, "downloadRunArtifact").mockResolvedValue({ arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer } as Blob);
  vi.stubGlobal("crypto", { subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).buffer) } });
  URL.createObjectURL = vi.fn().mockReturnValue("blob:preview");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("verifies bytes before preview and pauses hidden media", async () => {
  const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  const view = render(<ArtifactPreview file={file} />);
  await waitFor(() => expect(view.container.querySelector("video")).not.toBeNull());
  expect(api.downloadRunArtifact).toHaveBeenCalledWith(7, "sample.mp4");
  view.rerender(<ArtifactPreview file={file} visible={false} />);
  expect(pause).toHaveBeenCalledOnce();
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
});

it("does not allocate a media URL after an unmounted pending download", async () => {
  let finish!: (blob: Blob) => void;
  vi.mocked(api.downloadRunArtifact).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const view = render(<ArtifactPreview file={file} />);
  view.unmount();
  await act(async () => { finish({ arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer } as Blob); });
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("rejects changed bytes and never embeds executable HTML", async () => {
  render(<ArtifactPreview file={{ ...file, bytes: 4, filename: "sample.html" }} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("dock.previewUnavailable");
  expect(document.querySelector("iframe")).toBeNull();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("describes partial extraction without claiming only the beginning was read", async () => {
  vi.spyOn(api, 'extractAttachmentFile').mockResolvedValue({ text: '[page 1] first\n[page 4] last', chars: 29, truncated: true });
  const view = render(<ArtifactPreview file={{ ...file, filename: 'mixed.pdf' }} />);
  expect(await screen.findByText('attach.delivery_truncated')).toBeInTheDocument();
  expect(screen.queryByText('dock.truncated')).not.toBeInTheDocument();
  vi.mocked(api.extractAttachmentFile).mockResolvedValue({ text: 'complete', chars: 8, truncated: false });
  view.rerender(<ArtifactPreview file={{ ...file, filename: 'complete.pdf' }} />);
  await screen.findByText('complete');
  expect(screen.queryByText('attach.delivery_truncated')).not.toBeInTheDocument();
});

it("retains beginning-only wording for the raw text preview display cap", async () => {
  const bytes = new TextEncoder().encode('x'.repeat(100001));
  vi.mocked(api.downloadRunArtifact).mockResolvedValue({ arrayBuffer: async () => bytes.buffer } as Blob);
  render(<ArtifactPreview file={{ ...file, filename: 'large.txt', bytes: bytes.length }} />);
  expect(await screen.findByText('dock.truncated')).toBeInTheDocument();
  expect(screen.queryByText('attach.delivery_truncated')).not.toBeInTheDocument();
  expect(document.querySelector('pre')?.textContent?.length).toBe(100000);
});
