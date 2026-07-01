import { Presentation, Download } from 'lucide-react';

/**
 * DeckDownloadCard — renders a downloadable .pptx artifact from the backend render_deck tool.
 *
 * 🔒 SECURITY: `bytesB64` is populated ONLY from a backend render_deck tool_result artifact,
 * never from LLM message text — same invariant as artifactChart/artifactSvg. A .pptx is a binary
 * file (not inline-renderable like a chart), so it's offered as a download rather than embedded.
 */
const PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation';

function b64ToBlob(b64: string, mime: string): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

export default function DeckDownloadCard({
  filename,
  bytesB64,
  slides,
}: {
  filename: string;
  bytesB64: string;
  slides: number;
}) {
  const download = () => {
    const url = URL.createObjectURL(b64ToBlob(bytesB64, PPTX_MIME));
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'deck.pptx';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  };
  return (
    <div className="tool-chart flex items-center gap-2.5 max-w-md border border-border-strong bg-background/60 rounded-lg px-3 py-2.5 mt-2">
      <Presentation className="w-4 h-4 text-primary shrink-0" />
      <span className="text-[11.5px] text-foreground font-medium flex-1 truncate">
        {filename} · {slides} slides
      </span>
      <button
        type="button"
        onClick={download}
        title="Download .pptx"
        className="flex items-center gap-1 px-1.5 py-0.5 rounded text-subtle-foreground hover:text-primary hover:bg-primary/10 transition-colors text-[10.5px] font-mono"
      >
        <Download className="w-3 h-3" /> .pptx
      </button>
    </div>
  );
}
