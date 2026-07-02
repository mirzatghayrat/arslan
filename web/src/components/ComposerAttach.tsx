import { useRef, useState, useCallback } from "react";
import { Plus, X, Loader2, FileText } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";

/**
 * In-composer attach UX (replaces the old AttachBar-above-input).
 *
 * Architecture:
 *  - `useComposerAttach()` owns the state + the SSRF-hardened extract logic
 *    (file → extractAttachmentFile, url → extractAttachmentUrl). It returns
 *    handlers a composer wires onto its existing input box (drag-drop + paste +
 *    onInputChange) plus the data needed to render chips and the "+" control.
 *  - URLs are AUTO-DETECTED: when the user types a URL (followed by a space) or
 *    pastes one, it's extracted inline as a source — no button, the way
 *    ChatGPT/Gemini/Perplexity work. The only visible control is "+" for files.
 *  - `<AttachChips>` renders the file/image/url pills. Images go through the same
 *    /extract endpoint (backend OCR); when OCR finds no text the chip degrades
 *    honestly to preview-only (thumbnail stays either way).
 *  - `<AttachControl>` is the lower-left "+" button → native file/image picker.
 *
 * 🔒 SECURITY: URL extraction goes ONLY through api.extractAttachmentUrl, which
 * hits the SSRF-hardened backend /extract endpoint. No new fetch path is built.
 */

export interface Attachment {
  name: string;
  text: string;
  chars: number;
  truncated: boolean;
  /** Image chips carry an object-URL for the thumbnail. Their `text` is filled by
   *  backend OCR; it stays empty when no text is found (preview-only degrade). */
  kind?: "doc" | "image";
  previewUrl?: string;
  /** OCR lifecycle for image chips: extracting → text found / none found. */
  ocr?: "pending" | "ok" | "none";
}

/** Accept list for the native picker: existing doc types + images. */
export const ATTACH_ACCEPT = ".pdf,.docx,.txt,.md,image/*";
const DOC_EXT = /\.(pdf|docx|txt|md)$/i;
/** Per-message budget, borrowed from Kimi/DeepSeek (surface caps on reject). */
export const MAX_ATTACHMENTS = 9;
/** 30 MB/file, matching the Claude reference in the design doc. */
const MAX_FILE_BYTES = 30 * 1024 * 1024;
/** Explicit-scheme URLs with a TLD-like dot. Bare domains are intentionally NOT
 *  auto-detected (too ambiguous with filenames/prose). */
const URL_RE = /\bhttps?:\/\/[^\s<>"'`]+\.[a-z][^\s<>"'`]*/gi;
/** Detection debounce so we extract a settled URL, not each keystroke. */
const DETECT_DEBOUNCE_MS = 700;

/** Pull settled URLs out of text, trimming trailing sentence punctuation. */
function extractUrls(text: string): string[] {
  return Array.from(text.matchAll(URL_RE)).map((m) => m[0].replace(/[.,;:!?)\]}]+$/, ""));
}

export interface UseComposerAttach {
  attachments: Attachment[];
  busy: boolean;
  error: string | null;
  setError: (e: string | null) => void;
  dragActive: boolean;
  addFiles: (files: FileList | File[]) => Promise<void>;
  removeAt: (i: number) => void;
  clear: () => void;
  /** Feed the composer's current input text so typed URLs auto-extract (debounced). */
  onInputChange: (text: string) => void;
  /** Spread onto the composer's input wrapper to enable drag-and-drop. */
  dndHandlers: {
    onDragOver: (e: React.DragEvent) => void;
    onDragLeave: (e: React.DragEvent) => void;
    onDrop: (e: React.DragEvent) => void;
  };
  /** Attach to the textarea/input: pastes files, and auto-detects pasted URLs. */
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
  // URLs already handled (extracted or in flight), so re-scans don't re-extract.
  const handledUrls = useRef<Set<string>>(new Set());

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
          // Same /extract path as docs (backend OCR). Chip shows the thumbnail
          // immediately; OCR result fills `text`, or the chip degrades honestly
          // to preview-only when no text is found (incl. extract errors).
          const chip: Attachment = {
            name: file.name,
            text: "",
            chars: 0,
            truncated: false,
            kind: "image" as const,
            previewUrl: URL.createObjectURL(file),
            ocr: "pending" as const,
          };
          current = [...current, chip];
          commit(current);
          setBusy(true);
          let done: Attachment;
          try {
            const r = await api.extractAttachmentFile(file, compress);
            done = r.text.trim()
              ? { ...chip, text: r.text, chars: r.chars, truncated: r.truncated, ocr: "ok" as const }
              : { ...chip, ocr: "none" as const };
          } catch {
            done = { ...chip, ocr: "none" as const };
          } finally {
            setBusy(false);
          }
          current = current.map((a) => (a === chip ? done : a));
          commit(current);
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

  /** Extract one or more detected URLs into source chips (sequential; deduped; capped). */
  const addUrls = useCallback(
    async (urls: string[]) => {
      let current = attachments;
      for (const raw of urls) {
        const u = raw.trim();
        if (!u || current.some((a) => a.name === u)) continue;
        if (current.length >= MAX_ATTACHMENTS) {
          setError(t("attach.too_many", { max: MAX_ATTACHMENTS }));
          break;
        }
        setBusy(true);
        setError(null);
        try {
          // 🔒 SSRF-hardened backend path — do NOT replace with a direct fetch.
          const r = await api.extractAttachmentUrl(u, compress);
          const next = [
            ...current,
            { name: u, text: r.text, chars: r.chars, truncated: r.truncated, kind: "doc" as const },
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

  // scanRef always points at a closure over the LATEST attachments/addUrls, so the
  // debounced timer never fires against stale state (useEventCallback pattern).
  const scanRef = useRef<(text: string) => void>(() => {});
  scanRef.current = (text: string) => {
    const fresh = extractUrls(text).filter(
      (u) => !handledUrls.current.has(u) && !attachments.some((a) => a.name === u),
    );
    if (fresh.length === 0) return;
    fresh.forEach((u) => handledUrls.current.add(u));
    void addUrls(fresh);
  };

  const detectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onInputChange = useCallback((text: string) => {
    if (detectTimer.current) clearTimeout(detectTimer.current);
    detectTimer.current = setTimeout(() => scanRef.current(text), DETECT_DEBOUNCE_MS);
  }, []);

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
    handledUrls.current.clear();
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
      return;
    }
    // Pasted text: auto-extract any URL(s) immediately (the text still lands in the box).
    const text = e.clipboardData?.getData("text") ?? "";
    const fresh = extractUrls(text).filter(
      (u) => !handledUrls.current.has(u) && !attachments.some((a) => a.name === u),
    );
    if (fresh.length > 0) {
      fresh.forEach((u) => handledUrls.current.add(u));
      void addUrls(fresh);
    }
  };

  return { attachments, busy, error, setError, dragActive, addFiles, removeAt, clear, onInputChange, dndHandlers, onPaste };
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
              ? a.ocr === "pending"
                ? `· ${t("attach.image_ocr_wait")}`
                : a.ocr === "ok"
                  ? `· ${t("attach.image_ocr_ok")}`
                  : `· ${t("attach.image_no_parse")}`
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

/** The lower-left "+" control: native file/image picker. URLs auto-detect from the input. */
export function AttachControl({
  busy,
  onPickFiles,
}: {
  busy: boolean;
  onPickFiles: (files: FileList) => void;
}) {
  const { t } = useTranslation();
  const fileRef = useRef<HTMLInputElement>(null);

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
    </div>
  );
}
