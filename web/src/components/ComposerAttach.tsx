import { useEffect, useRef, useState, useCallback } from "react";
import { fileToImagePayload, type ImagePayload } from "../lib/imagePayload";
import { Plus, X, Loader2, FileText } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { INPUT_ACCEPT, INPUT_FORMATS, documentInputSupported, inputKind } from "../lib/inputFormats";
import type { MessageAttachment } from "../types";
import type { AttachmentDraft } from '../lib/composerDrafts';

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
  /** OCR lifecycle for image chips: extracting → text found / none found.
   *  Since the vision round this is only reached when an image could NOT be
   *  prepared for the model; a normal image chip carries `image` instead. */
  ocr?: "pending" | "ok" | "none";
  /** The downscaled base64 the model actually receives. Present ⇒ this image
   *  rides the turn as a real image block, not as OCR'd text. */
  image?: ImagePayload;
  images?: ImagePayload[];
  videoFrameStatus?: string;
  inputKind?: string;
}

export function attachmentImages(items: Attachment[]): ImagePayload[] {
  return items.flatMap(item => [...(item.image ? [item.image] : []), ...(item.images ?? [])]);
}

/** Preserve extraction limits in both the model context and the sent-message echo. */
export function attachmentDelivery(items: Attachment[], t: (key: string) => string) {
  const display: MessageAttachment[] = [];
  const sources: { name: string; text: string }[] = [];
  for (const item of items) {
    const hasImages = attachmentImages([item]).length > 0;
    const status: MessageAttachment['extractionStatus'] = item.truncated ? 'truncated'
      : item.kind === 'image' && !hasImages && !item.text.trim() ? 'image_unavailable'
      : !hasImages && !item.text.trim() ? 'empty' : undefined;
    display.push({ name: item.name, kind: item.kind, previewUrl: item.previewUrl,
      ...(status ? { extractionStatus: status } : {}) });
    const text = status
      ? `[${JSON.stringify(item.name)}: ${t(`attach.delivery_${status}`)}]\n${item.text}`
      : item.text;
    if (text) sources.push({ name: item.name, text });
  }
  return { display, sources };
}

export function attachmentImageBudgetExceeded(items: Attachment[]): boolean {
  const images = attachmentImages(items);
  return images.length > 9 || images.reduce((sum, item) => sum + item.data.length, 0) > 12 * 1024 * 1024;
}

/** Accept list for the native picker: existing doc types + images. */
const ATTACH_ACCEPT = INPUT_ACCEPT;
/** Per-message budget, borrowed from Kimi/DeepSeek (surface caps on reject). */
const MAX_ATTACHMENTS = 9;
/** 30 MB/file, matching the Claude reference in the design doc. */
const MAX_FILE_BYTES = INPUT_FORMATS.max_bytes;
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
  /** Clear all chips. Pass { revokeUrls: false } on SEND so the message bubble can keep
   *  rendering image thumbnails from the object-URLs (session-only; see clear()). */
  clear: (opts?: { revokeUrls?: boolean }) => void;
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
  { allowUrlExtraction = true, draft }: { allowUrlExtraction?: boolean; draft?: AttachmentDraft } = {},
): UseComposerAttach {
  const { t } = useTranslation();
  // The owner remounts this hook when conversation/privacy changes.
  const [attachments, setAttachments] = useState<Attachment[]>(() => draft?.items ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const dragDepth = useRef(0);
  // URLs already handled (extracted or in flight), so re-scans don't re-extract.
  const handledUrls = useRef<Set<string>>(new Set());
  const urlPolicy = useRef({ allowed: allowUrlExtraction, revision: 0 });
  if (urlPolicy.current.allowed !== allowUrlExtraction) {
    urlPolicy.current = { allowed: allowUrlExtraction, revision: urlPolicy.current.revision + 1 };
  }
  const currentItems = useRef<Attachment[]>(attachments);
  const generation = useRef(0);
  const mounted = useRef(true);
  const changeCallback = useRef(onChange);
  changeCallback.current = onChange;
  // True reserves an invisible document/URL slot; image placeholders already
  // occupy their slot. Tokens also keep busy correct across overlapping batches.
  const pending = useRef(new Map<object, boolean>());
  const start = useCallback((reserve: boolean) => {
    const token = {};
    pending.current.set(token, reserve);
    setBusy(true);
    return token;
  }, []);
  const finish = useCallback((token: object) => {
    pending.current.delete(token);
    if (mounted.current) setBusy(pending.current.size > 0);
  }, []);
  const valid = useCallback((epoch: number) => mounted.current && !draft?.discarded && generation.current === epoch, [draft]);
  const full = useCallback(() => currentItems.current.length
    + [...pending.current.values()].filter(Boolean).length >= MAX_ATTACHMENTS, []);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      pending.current.clear();
      const retained = draft && !draft.discarded
        ? currentItems.current.filter(item => item.ocr !== 'pending') : [];
      for (const item of currentItems.current) {
        if (!retained.includes(item) && item.previewUrl && !draft?.discarded) URL.revokeObjectURL(item.previewUrl);
      }
      if (draft && !draft.discarded) draft.items = retained;
      currentItems.current = retained;
    };
  }, [draft]);

  const commit = useCallback(
    (next: Attachment[]) => {
      if (!mounted.current || draft?.discarded) return;
      currentItems.current = next;
      if (draft) draft.items = next;
      setAttachments(next);
      changeCallback.current(next);
    },
    [draft],
  );

  const isImage = (f: File) =>
    !/\.svg$/i.test(f.name) && (f.type.startsWith("image/") || inputKind(f.name) === "image");

  const addFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      if (list.length === 0) return;
      setError(null);
      const epoch = generation.current;
      for (const file of list) {
        if (!valid(epoch)) return;
        if (full()) {
          setError(t("attach.too_many", { max: MAX_ATTACHMENTS }));
          break;
        }
        if (file.size > MAX_FILE_BYTES) {
          setError(t("attach.too_large", { name: file.name }));
          continue;
        }
        if (isImage(file)) {
          // Vision round: the MODEL reads the image, so there is nothing to
          // extract server-side. The chip is prepared locally (downscale +
          // base64, see lib/imagePayload) and rides the turn as an image block.
          // The old /extract round-trip only ever produced "" in the packaged
          // app — there is no OCR stack there — which is what made images
          // "preview only".
          const chip: Attachment = {
            name: file.name,
            text: "",
            chars: 0,
            truncated: false,
            kind: "image" as const,
            previewUrl: URL.createObjectURL(file),
            ocr: "pending" as const,
          };
          commit([...currentItems.current, chip]);
          const token = start(false);
          let done: Attachment;
          try {
            done = { ...chip, image: await fileToImagePayload(file), ocr: undefined };
          } catch {
            // Unreadable or too large even after downscaling: say so on the chip
            // rather than sending a frame that would kill the socket.
            done = { ...chip, ocr: "none" as const };
          } finally {
            finish(token);
          }
          if (!valid(epoch)) return;
          if (currentItems.current.includes(chip)) {
            commit(currentItems.current.map((a) => (a === chip ? done : a)));
          }
          continue;
        }
        if (!documentInputSupported(file.name)) {
          setError(t("attach.unsupported", { name: file.name }));
          continue;
        }
        const token = start(true);
        try {
          const r = await api.extractAttachmentFile(file, compress);
          if (!valid(epoch)) return;
          pending.current.set(token, false);
          const next = [
            ...currentItems.current,
            { name: file.name, text: r.text, chars: r.chars, truncated: r.truncated, kind: "doc" as const, inputKind: inputKind(file.name), images: r.images, videoFrameStatus: r.video_frame_status },
          ];
          commit(next);
        } catch (e) {
          if (!valid(epoch)) return;
          const detail = e && typeof e === "object" && "detail" in e ? e.detail : null;
          const code = detail && typeof detail === "object" && "code" in detail ? String(detail.code) : "";
          setError(t(["inputs.limit", "inputs.invalid", "inputs.encoding", "inputs.unsupported", "inputs.videoToolMissing"].includes(code) ? code : "inputs.failed"));
        } finally {
          finish(token);
        }
      }
    },
    [commit, compress, t, start, finish, valid, full],
  );

  /** Extract one or more detected URLs into source chips (sequential; deduped; capped). */
  const addUrls = useCallback(
    async (urls: string[]) => {
      const epoch = generation.current;
      const policyRevision = urlPolicy.current.revision;
      const allowed = () => valid(epoch) && urlPolicy.current.allowed
        && urlPolicy.current.revision === policyRevision;
      for (const raw of urls) {
        if (!allowed()) return;
        const u = raw.trim();
        if (!u || currentItems.current.some((a) => a.name === u)) continue;
        if (full()) {
          setError(t("attach.too_many", { max: MAX_ATTACHMENTS }));
          break;
        }
        const token = start(true);
        setError(null);
        try {
          // 🔒 SSRF-hardened backend path — do NOT replace with a direct fetch.
          const r = await api.extractAttachmentUrl(u, compress);
          if (!allowed()) return;
          pending.current.set(token, false);
          const next = [
            ...currentItems.current,
            { name: u, text: r.text, chars: r.chars, truncated: r.truncated, kind: "doc" as const },
          ];
          commit(next);
        } catch (e) {
          if (!allowed()) return;
          setError(String((e as Error).message ?? e));
        } finally {
          finish(token);
        }
      }
    },
    [commit, compress, t, start, finish, valid, full],
  );

  // scanRef always points at a closure over the LATEST attachments/addUrls, so the
  // debounced timer never fires against stale state (useEventCallback pattern).
  const scanRef = useRef<(text: string) => void>(() => {});
  scanRef.current = (text: string) => {
    if (!allowUrlExtraction) return;
    const fresh = extractUrls(text).filter(
      (u) => !handledUrls.current.has(u) && !attachments.some((a) => a.name === u),
    );
    if (fresh.length === 0) return;
    fresh.forEach((u) => handledUrls.current.add(u));
    void addUrls(fresh);
  };

  const detectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (detectTimer.current) clearTimeout(detectTimer.current); }, []);
  const onInputChange = useCallback((text: string) => {
    if (detectTimer.current) clearTimeout(detectTimer.current);
    detectTimer.current = setTimeout(() => scanRef.current(text), DETECT_DEBOUNCE_MS);
  }, []);

  const removeAt = useCallback(
    (i: number) => {
      const target = currentItems.current[i];
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      commit(currentItems.current.filter((_, idx) => idx !== i));
    },
    [commit],
  );

  const clear = useCallback((opts?: { revokeUrls?: boolean }) => {
    generation.current += 1;
    pending.current.clear();
    if (detectTimer.current) clearTimeout(detectTimer.current);
    // On SEND the caller passes { revokeUrls: false }: the sent user bubble renders image
    // thumbnails straight from these object-URLs, so they must stay alive. They are never
    // revoked afterwards — an accepted small session-only leak (object-URLs die on reload,
    // and revoking on thread switch would blank thumbnails of still-mounted messages).
    if (opts?.revokeUrls !== false) {
      for (const a of currentItems.current) if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
    }
    handledUrls.current.clear();
    commit([]);
    setBusy(false);
    setError(null);
  }, [commit]);

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
    if (!allowUrlExtraction) return;
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
          <span className="attach-chip__details">
          <span className="attach-chip__name" title={a.name}>{a.name}</span>
          <span className="attach-chip__meta">
            {a.kind === "image"
              ? a.image
                // The disclosure the spec requires at the feed entry point: the
                // user is about to send a picture to a CLOUD model and may well
                // assume a local-first app reads it locally.
                ? `· ${t("attach.image_goes_to_model")}`
                : a.ocr === "pending"
                  ? `· ${t("attach.image_ocr_wait")}`
                  : `· ${t("attach.image_unsendable")}`
              : `· ${t("attach.chars", { n: a.chars })}${a.truncated ? t("attach.truncated") : ""}${a.inputKind === "video" ? ` · ${a.images?.length ? t("inputs.videoSamples", { count: a.images.length }) : t("inputs.videoMetadataOnly")}` : a.inputKind === "spreadsheet" ? ` · ${t("inputs.cachedValues")}` : a.inputKind === "presentation" ? ` · ${t("inputs.slideTextOnly")}` : ""}`}
          </span>
          {a.inputKind === "video" && !a.images?.length && a.videoFrameStatus && (
            <span className="attach-chip__meta">
              {a.videoFrameStatus === "tool_missing" ? t("inputs.videoToolMissing") : t("inputs.videoSamplingFailed")}
            </span>
          )}
          </span>
          <button
            type="button"
            aria-label={t('ui.removeAttachment')}
            onClick={() => onRemove(i)}
          >
            <X className="w-3 h-3" />
          </button>
        </span>
      ))}
    </div>
  );
}

/** Attachments echoed inside a SENT user bubble (both chats). Image chips with a live
 *  object-URL render a small thumbnail; everything else — docs/urls, and history-restored
 *  items whose object-URLs are gone (previewUrl is session-only, never persisted) — falls
 *  back to a compact file chip. No broken-image icons, no empty block: renders nothing
 *  when there are no attachments. */
export function SentAttachments({ attachments }: { attachments?: MessageAttachment[] }) {
  const { t } = useTranslation();
  if (!attachments || attachments.length === 0) return null;
  return (
    <div className="sent-attachments">
      {attachments.map((a, i) =>
        a.kind === "image" && a.previewUrl && !a.extractionStatus ? (
          <img key={`${a.name}-${i}`} src={a.previewUrl} alt={a.name} className="sent-attachment__img" />
        ) : (
          <span key={`${a.name}-${i}`} className="sent-attachment__chip" title={a.name}>
            <FileText className="w-3 h-3 shrink-0" />
            <span className="sent-attachment__details">
              <span className="sent-attachment__name">{a.name}</span>
              {a.extractionStatus && <span className="sent-attachment__status">{t(`attach.delivery_${a.extractionStatus}`)}</span>}
            </span>
          </span>
        ),
      )}
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
