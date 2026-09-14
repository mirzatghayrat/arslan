import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { StoredArtifact } from "../api/client.types";
import ArtifactDownloads from "./ArtifactDownloads";
import { INPUT_FORMATS } from "../lib/inputFormats";

export default function ArtifactPreview({ file, visible = true }: { file: StoredArtifact; visible?: boolean }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [kind, setKind] = useState<"image" | "video" | "audio" | "text" | null>(null);
  const [error, setError] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const mediaElement = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  useEffect(() => { if (!visible) mediaElement.current?.pause(); }, [visible]);
  useEffect(() => {
    let active = true; let objectUrl: string | null = null;
    setError(false); setText(null); setKind(null); setUrl(null); setTruncated(false);
    void (async () => {
      if (file.bytes > 50 * 1024 * 1024) throw new Error("preview limit");
      const blob = await api.downloadRunArtifact(file.run_id, file.filename);
      const bytes = await blob.arrayBuffer();
      if (bytes.byteLength !== file.bytes) throw new Error("file changed");
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), byte => byte.toString(16).padStart(2, "0")).join("");
      if (digest !== file.sha256) throw new Error("file changed");
      if (!active) return;
      const extension = file.filename.split(".").pop()?.toLowerCase() ?? "";
      const media: Record<string, ["image" | "video" | "audio", string]> = {
        png: ["image", "image/png"], jpg: ["image", "image/jpeg"], jpeg: ["image", "image/jpeg"], webp: ["image", "image/webp"], gif: ["image", "image/gif"], bmp: ["image", "image/bmp"],
        mp4: ["video", "video/mp4"], webm: ["video", "video/webm"], mov: ["video", "video/quicktime"],
        mp3: ["audio", "audio/mpeg"], wav: ["audio", "audio/wav"], m4a: ["audio", "audio/mp4"], ogg: ["audio", "audio/ogg"],
      };
      if (media[extension]) {
        objectUrl = URL.createObjectURL(new Blob([bytes], { type: media[extension][1] }));
        if (active) { setKind(media[extension][0]); setUrl(objectUrl); }
      } else if ([...INPUT_FORMATS.text, "html", "htm"].includes(extension)) {
        const content = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        if (active) { setKind("text"); setText(content.slice(0, 100000)); setTruncated(content.length > 100000); }
      } else {
        const extracted = await api.extractAttachmentFile(new File([bytes], file.filename));
        if (active) { setKind("text"); setText(extracted.text); setTruncated(extracted.truncated); }
      }
    })().catch(() => { if (active) setError(true); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [file.run_id, file.filename, file.sha256, file.bytes]);
  return <div className="h-full space-y-4 overflow-y-auto p-4">
    <h3 className="break-words text-sm font-medium">{file.title}</h3>
    <p className="text-xs text-muted-foreground">{t("dock.fileLimits")}</p>
    {error && <p role="alert" className="text-sm text-destructive">{t("dock.previewUnavailable")}</p>}
    {!kind && !error && <p role="status">{t("browser.loading")}</p>}
    {kind === "image" && url && <img src={url} alt={file.title} className="max-w-full" onError={() => setError(true)} />}
    {kind === "video" && url && <video ref={mediaElement} controls preload="metadata" src={url} className="w-full" onError={() => setError(true)} />}
    {kind === "audio" && url && <audio ref={mediaElement} controls preload="metadata" src={url} className="w-full" onError={() => setError(true)} />}
    {kind === "text" && <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">{text}</pre>}
    {truncated && <p role="status" className="text-xs text-muted-foreground">{t("dock.truncated")}</p>}
    <ArtifactDownloads files={[file]} preview={false} />
  </div>;
}
