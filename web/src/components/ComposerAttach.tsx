import { useRef, useState, useCallback } from "react";
import { Plus, Link as LinkIcon, X, Loader2, FileText } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";

/**
 * In-composer attach UX (replaces the old AttachBar-above-input).
 *
 * Architecture:
 *  - `useComposerAttach()` owns the state + the SSRF-hardened extract logic
 *    (file → extractAttachmentFile, url → extractAttachmentUrl). It returns
 *    handlers a composer wires onto its existing input box (drag-drop + paste)
 *    plus the data needed to render chips and the "+" control.
 *  - `<AttachChips>` renders the file/image pills (image = honest preview-only
 *    thumbnail, since the doc-ingest backend can't read images).
 *  - `<AttachControl>` is the lower-left "+" button → file picker + a URL field
 *    revealed on demand.
 *
 * 🔒 SECURITY: URL extraction goes ONLY through api.extractAttachmentUrl, which
 * hits the SSRF-hardened backend /extract endpoint. No new fetch path is built.
 */

export interface Attachment {
  name: string;
  text: string;
  chars: number;
  truncated: boolean;
  /** Preview-only image (doc-ingest backend can't read it). Carries an object-URL
   *  for the thumbnail; `text` stays empty so it contributes nothing to context. */
  kind?: "doc" | "image";
  previewUrl?: string;
}

/** Accept list for the native picker: existing doc types + images. */
export const ATTACH_ACCEPT = ".pdf,.docx,.txt,.md,image/*";
const DOC_EXT = /\.(pdf|docx|txt|md)$/i;
/** Per-message budget, borrowed from Kimi/DeepSeek (surface caps on reject). */
export const MAX_ATTACHMENTS = 9;
/** 30 MB/file, matching the Claude reference in the design doc. */
const MAX_FILE_BYTES = 30 * 1024 * 1024;

export interface UseComposerAttach {
  attachments: Attachment[];
  busy: boolean;
  error: string | null;
  setError: (e: string | null) => void;
  dragActive: boolean;
  addFiles: (files: FileList | File[]) => Promise<void>;
  addUrl: (url: string) => Promise<boolean>;
  removeAt: (i: number) => void;
  clear: () => void;
  /** Spread onto the composer's input wrapper to enable drag-and-drop. */
  dndHandlers: {
    onDragOver: (e: React.DragEvent) => void;
    onDragLeave: (e: React.DragEvent) => void;
    onDrop: (e: React.DragEvent) => void;
  };
  /** Attach to the textarea/input to enable paste-to-attach (returns true if it consumed files). */
  onPaste: (e: React.ClipboardEvent) => void;
}

export function useComposerAttach(
  onChange: (items: Attachment[]) => void,
  compress = false,
): UseComposerAttach {
  const { t } = useTranslation();
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const dragDepth = useRef(0);

  const commit = useCallback(
    (next: Attachment[]) => {
      setAttachments(next);
      onChange(next);
    },
    [onChange],
  );

  const isImage = (f: File) =>
    f.type.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(f.name);

  const addFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      if (list.length === 0) return;
      setError(null);
      let current = attachments;
      for (const file of list) {
        if (current.length >= MAX_ATTACHMENTS) {
          setError(t("attach.too_many", { max: MAX_ATTACHMENTS }));
          break;
        }
        if (file.size > MAX_FILE_BYTES) {
          setError(t("attach.too_large", { name: file.name }));
          continue;
        }
        if (isImage(file)) {
          // Honest degrade: images aren't ingestable as docs. Preview-only chip,
          // empty text so it never silently injects into context.
          const next = [
            ...current,
            {
              name: file.name,
              text: "",
              chars: 0,
              truncated: false,
              kind: "image" as const,
              previewUrl: URL.createObjectURL(file),
            },
          ];
          current = next;
          commit(next);
          continue;
        }
        if (!DOC_EXT.test(file.name)) {
          setError(t("attach.unsupported", { name: file.name }));
          continue;
        }
        setBusy(true);
        try {
          const r = await api.extractAttachmentFile(file, compress);
          const next = [
            ...current,
            { name: file.name, text: r.text, chars: r.chars, truncated: r.truncated, kind: "doc" as const },
          ];
          current = next;
          commit(next);
        } catch (e) {
          setError(String((e as Error).message ?? e));
        } finally {
          setBusy(false);
        }
      }
    },
    [attachments, commit, compress, t],
  );

  const addUrl = useCallback(
    async (url: string): Promise<boolean> => {
      const u = url.trim();
      if (!u || busy) return false;
      if (attachments.length >= MAX_ATTACHMENTS) {
        setError(t("attach.too_many", { max: MAX_ATTACHMENTS }));
        return false;
      }
      setBusy(true);
      setError(null);
      try {
        // 🔒 SSRF-hardened backend path — do NOT replace with a direct fetch.
        const r = await api.extractAttachmentUrl(u, compress);
        commit([...attachments, { name: u, text: r.text, chars: r.chars, truncated: r.truncated, kind: "doc" }]);
        return true;
      } catch (e) {
        setError(String((e as Error).message ?? e));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [attachments, busy, commit, compress, t],
  );

  const removeAt = useCallback(
    (i: number) => {
      const target = attachments[i];
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      commit(attachments.filter((_, idx) => idx !== i));
    },
    [attachments, commit],
  );

  const clear = useCallback(() => {
    for (const a of attachments) if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
    setAttachments([]);
    setError(null);
    onChange([]);
  }, [attachments, onChange]);

  const dndHandlers = {
    onDragOver: (e: React.DragEvent) => {
      if (Array.from(e.dataTransfer?.types ?? []).includes("Files")) {
        e.preventDefault();
        setDragActive(true);
      }
    },
    onDragLeave: (e: React.DragEvent) => {
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (dragDepth.current === 0) setDragActive(false);
      void e;
    },
    onDrop: (e: React.DragEvent) => {
      const files = e.dataTransfer?.files;
      if (files && files.length > 0) {
        e.preventDefault();
        dragDepth.current = 0;
        setDragActive(false);
        void addFiles(files);
      }
    },
  };

  const onPaste = (e: React.ClipboardEvent) => {
    const files = e.clipboardData?.files;
    if (files && files.length > 0) {
      e.preventDefault();
      void addFiles(files);
    }
  };

  return { attachments, busy, error, setError, dragActive, addFiles, addUrl, removeAt, clear, dndHandlers, onPaste };
}

/** Chips/pills rendered inside the composer (below the input). */
export function AttachChips({
  attachments,
  onRemove,
}: {
  attachments: Attachment[];
  onRemove: (i: number) => void;
}) {
  const { t } = useTranslation();
  if (attachments.length === 0) return null;
  return (
    <div className="attach-chips">
      {attachments.map((a, i) => (
        <span key={i} className={`attach-chip${a.kind === "image" ? " attach-chip--image" : ""}`}>
          {a.kind === "image" && a.previewUrl ? (
            <img src={a.previewUrl} alt={a.name} className="attach-chip__thumb" />
          ) : (
            <FileText className="w-3 h-3 shrink-0" />
          )}
          <span className="attach-chip__name">{a.name}</span>
          <span className="attach-chip__meta">
            {a.kind === "image"
              ? `· ${t("attach.image_no_parse")}`
              : `· ${t("attach.chars", { n: a.chars })}${a.truncated ? t("attach.truncated") : ""}`}
          </span>
          <button
            type="button"
            aria-label="remove-attachment"
            onClick={() => onRemove(i)}
          >
            <X className="w-3 h-3" />
          </button>
        </span>
      ))}
    </div>
  );
}

/** The lower-left "+" control: native picker + on-demand URL field. */
export function AttachControl({
  busy,
  onPickFiles,
  onAddUrl,
}: {
  busy: boolean;
  onPickFiles: (files: FileList) => void;
  onAddUrl: (url: string) => Promise<boolean> | void;
}) {
  const { t } = useTranslation();
  const fileRef = useRef<HTMLInputElement>(null);
  const [showUrl, setShowUrl] = useState(false);
  const [url, setUrl] = useState("");

  const submitUrl = async () => {
    if (!url.trim()) return;
    const ok = await onAddUrl(url.trim());
    if (ok) {
      setUrl("");
      setShowUrl(false);
    }
  };

  return (
    <div className="attach-control">
      <button
        type="button"
        className="attach-add"
        title={t("attach.add")}
        aria-label={t("attach.add")}
        disabled={busy}
        onClick={() => fileRef.current?.click()}
      >
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
      </button>
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={ATTACH_ACCEPT}
        style={{ display: "none" }}
        onChange={(e) => {
          if (e.target.files && e.target.files.length > 0) onPickFiles(e.target.files);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        className={`attach-url-toggle${showUrl ? " attach-url-toggle--on" : ""}`}
        title={t("attach.url")}
        aria-label={t("attach.url")}
        onClick={() => setShowUrl((v) => !v)}
      >
        <LinkIcon className="w-3.5 h-3.5" />
      </button>
      {showUrl && (
        <input
          className="attach-url"
          autoFocus
          placeholder={t("attach.url_placeholder")}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void submitUrl();
            } else if (e.key === "Escape") {
              setShowUrl(false);
              setUrl("");
            }
          }}
        />
      )}
      {showUrl && (
        <button type="button" className="attach-read" disabled={busy} onClick={() => void submitUrl()}>
          {t("attach.read")}
        </button>
      )}
    </div>
  );
}
