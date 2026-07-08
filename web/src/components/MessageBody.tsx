/**
 * MessageBody — wraps assistant/spawn message text with long-output handling:
 *   1. Full-HTML documents (`<!DOCTYPE html>…`) render as a compact card + sandboxed
 *      preview instead of an escaped wall (Markdown.tsx deliberately omits rehype-raw).
 *   2. Long prose collapses in-bubble (max-height clamp + fade + Show more / 收起).
 *   3. A subtle export row. The .md/.html download buttons belong ONLY to the long-output
 *      collapse box — "boxed ⇔ downloadable" is one rule (same LONG_CHARS condition), so
 *      short/normal conversational replies never grow download buttons. Copy keeps its own
 *      lower threshold for messages whose parent renders no persistent action row.
 *
 * 🔒 SECURITY: the HTML preview is a fully sandboxed <iframe srcDoc> with NO sandbox
 * flags (no scripts, no same-origin) — untrusted model HTML is rendered isolated and
 * can never reach the app DOM or our origin. Never relax this to allow-same-origin.
 */
import React, { useState, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Check, Download, ChevronDown, ChevronUp, Eye, X, FileCode } from 'lucide-react';
import Markdown from './Markdown';

const LONG_CHARS = 1800;      // prose longer than this collapses in-bubble AND gets .md/.html downloads
const COPY_MIN_CHARS = 240;   // shorter messages don't get a standalone copy row (keeps chat clean)
const CLAMP_PX = 360;         // collapsed height

function isFullHtmlDoc(s: string): boolean {
  const t = s.trimStart();
  return /^<!doctype html/i.test(t) || (/^<html[\s>]/i.test(t) && /<\/html>/i.test(s));
}

// A doc cut by max-tokens has no </html>; only salvage it as a deliverable when there
// is substantial content after the doctype (backend parity: html_artifact.MIN_TRUNCATED_CHARS).
const MIN_TRUNCATED_CHARS = 2000;

/**
 * Deterministic salvage for an HTML document EMBEDDED in a reply (live incident:
 * the skill mandates a bare `<!DOCTYPE html` reply, but the model prefixed "以下是…完整
 * HTML 代码" + a ```html fence — so the doc rendered as a code wall instead of the
 * preview/download card). Don't bet on model obedience: if the text contains a
 * substantial `<!doctype html …` block anywhere (fenced or not), split it out:
 *   • closed (`</html>` present, ≥ 400 chars) → complete doc, unchanged behavior;
 *   • UNCLOSED with ≥ 2000 chars after the doctype → TRUNCATED doc (max-tokens cut it —
 *     msg 465 shape), salvaged to the end of the text with truncated: true. This is the
 *     rescue path for already-persisted history rows that predate the HX-2 backend channel.
 * Returns null when there is no salvageable doc (then normal rendering applies).
 */
function extractEmbeddedHtmlDoc(s: string): { pre: string; html: string; truncated: boolean } | null {
  const start = s.search(/<!doctype html/i);
  if (start < 0) return null;
  // Preamble: text before the doc, minus a dangling opening fence (```html / ~~~).
  const pre = s.slice(0, start).replace(/(^|\n)\s*(`{3,}|~{3,})[a-z]*\s*$/i, "").trimEnd();
  const endMatch = /<\/html>/i.exec(s.slice(start));
  if (endMatch) {
    const end = start + endMatch.index + endMatch[0].length;
    const html = s.slice(start, end);
    if (html.length < 400) return null; // not a real document (fenced teaching snippet etc.)
    return { pre, html, truncated: false };
  }
  // No </html>: the doc was cut by max-tokens. Sub-threshold → a small unclosed
  // snippet, leave the message alone.
  if (s.length - start < MIN_TRUNCATED_CHARS) return null;
  return { pre, html: s.slice(start), truncated: true };
}

/**
 * Export heuristic (user feedback: an exported report began with the conversational
 * preamble "I now have enough research data to compile… I will now generate the PPT").
 * The deliverable proper starts at its first markdown heading — the renderer's styled
 * title (the `|`-bar look) is just h1/h2 styling, so "first heading line" covers it.
 *
 * Rule: if the text contains a `# ` / `## ` / `### ` heading line (up to 3 leading
 * spaces allowed, lines inside ``` fences ignored), the export starts at the FIRST
 * such line and everything before it is dropped. Fallbacks — never a gutted export:
 *   • no heading → full text unchanged;
 *   • heading is the first line → full text (nothing to strip);
 *   • stripping would leave < 40% of the original characters → full text.
 * Export-only: copy button and on-screen rendering always use the full text.
 */
export function exportMarkdown(text: string): string {
  const lines = text.split('\n');
  let inFence = false;
  let idx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*(```|~~~)/.test(lines[i])) { inFence = !inFence; continue; }
    if (!inFence && /^ {0,3}#{1,3} /.test(lines[i])) { idx = i; break; }
  }
  if (idx <= 0) return text;
  const stripped = lines.slice(idx).join('\n');
  if (stripped.length < text.length * 0.4) return text;
  return stripped;
}

/** Blob → object URL → synthetic-anchor download. Shared with RunReplay's md/json export. */
export function triggerDownload(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

/** Wrap rendered markdown HTML in a standalone, theme-matched document for .html export. */
function buildStandaloneHtml(innerHtml: string, title: string): string {
  const root = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => root.getPropertyValue(name).trim() || fallback;
  const vars = [
    `--color-foreground:${v('--color-foreground', '#e7e7ea')}`,
    `--color-muted-foreground:${v('--color-muted-foreground', '#a9a9b3')}`,
    `--color-primary:${v('--color-primary', '#e8852b')}`,
    `--color-border:${v('--color-border', '#2a2a2e')}`,
    `--color-border-strong:${v('--color-border-strong', '#3a3a40')}`,
    `--color-background:${v('--color-background', '#0e0e10')}`,
    `--color-surface-raised:${v('--color-surface-raised', '#1a1a1d')}`,
    `--color-subtle-foreground:${v('--color-subtle-foreground', '#8a8a92')}`,
    `--color-success:${v('--color-success', '#3fb950')}`,
  ].join(';');
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${title}</title>
<style>:root{${vars}}html{color-scheme:dark}body{margin:0 auto;max-width:820px;padding:40px 28px;background:var(--color-background);color:var(--color-foreground);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.65}a{color:var(--color-primary)}table{border-collapse:collapse;width:100%}pre{overflow:auto}img{max-width:100%}</style>
</head><body>${innerHtml}</body></html>`;
}

function ActionButton({ onClick, title, children }: { onClick: () => void; title: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="flex items-center gap-1 px-1.5 py-0.5 rounded text-subtle-foreground hover:text-primary hover:bg-primary/10 transition-colors"
    >
      {children}
    </button>
  );
}

/**
 * Shared HTML-deliverable card: compact row + sandboxed-iframe preview + .html download.
 * Used for (a) full/embedded HTML docs detected in message text (this file) and
 * (b) the live kind:"html" stream_end artifact (HX-2 channel, OrchestratorChat).
 * `truncated` marks a max-tokens-cut doc: 「⚠ 输出被截断」 badge + incomplete note.
 * 🔒 `html` comes only from THIS message's text or a backend artifact frame — the
 * iframe stays sandbox="" (no scripts, no same-origin) in both cases.
 */
export function HtmlDocCard({
  html,
  indent = false,
  hasMessageActions = false,
  title,
  filename,
  bytes,
  truncated = false,
}: {
  html: string;
  indent?: boolean;
  hasMessageActions?: boolean;
  /** Artifact title (kind:"html" frame) — shown instead of the generic label. */
  title?: string;
  /** Server-side artifact filename — used as the download name when present. */
  filename?: string;
  /** Stored size in bytes (artifact frame); falls back to html.length. */
  bytes?: number;
  /** True when the doc was cut by max-tokens (no </html>). */
  truncated?: boolean;
}) {
  const { t } = useTranslation();
  const [preview, setPreview] = useState(false);
  const [copied, setCopied] = useState(false);
  const kb = Math.max(1, Math.round((bytes ?? html.length) / 1024));

  const copy = useCallback(() => {
    navigator.clipboard.writeText(html).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }, [html]);

  return (
    <div className={indent ? 'pl-5' : ''} data-testid="html-doc-card">
      <div className="flex items-center gap-2.5 max-w-md border border-border-strong bg-background/60 rounded-lg px-3 py-2.5">
        <FileCode className="w-4 h-4 text-primary shrink-0" />
        <span className="text-[11.5px] text-foreground font-medium flex-1">
          {title ? `${title} · ${kb} KB` : t('msg.html_doc', { kb })}
          {truncated && (
            <span className="ml-2 text-[9.5px] font-mono px-1.5 py-0.5 rounded bg-warning/15 text-warning align-middle">
              {t('msg.html_truncated')}
            </span>
          )}
        </span>
        <div className="flex items-center gap-0.5 text-[10.5px] font-mono">
          <ActionButton onClick={() => setPreview(true)} title={t('msg.preview')}>
            <Eye className="w-3 h-3" /> {t('msg.preview')}
          </ActionButton>
          {/* For an HTML-doc deliverable the card IS the whole message, so a card-copy would
              duplicate the message row's copy (identical string). Defer to the row when it exists;
              keep card-copy for non-deliverable HTML (no message row). preview/download always stay. */}
          {!hasMessageActions && (
            <ActionButton onClick={copy} title={t('msg.copy')}>
              {copied ? <Check className="w-3 h-3 text-success" /> : <Copy className="w-3 h-3" />}
            </ActionButton>
          )}
          <ActionButton
            onClick={() => triggerDownload(filename ?? `document-${Date.now()}.html`, html, 'text/html;charset=utf-8')}
            title={t('msg.download_html')}
          >
            <Download className="w-3 h-3" /> .html
          </ActionButton>
        </div>
      </div>

      {truncated && (
        <div className="mt-1 text-[10px] font-mono text-warning/90">
          {t('msg.html_incomplete')}
        </div>
      )}

      {preview && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-6"
          onClick={() => setPreview(false)}
        >
          <div
            className="w-full max-w-4xl h-[80vh] flex flex-col bg-surface border border-border-strong rounded-xl overflow-hidden shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-surface-raised">
              <div className="flex items-center gap-2 text-[11.5px] font-mono text-muted-foreground">
                <FileCode className="w-3.5 h-3.5 text-primary" />
                <span>{t('msg.html_preview')}</span>
                <span className="text-subtle-foreground">· {kb} KB</span>
              </div>
              <button
                type="button"
                onClick={() => setPreview(false)}
                className="text-subtle-foreground hover:text-foreground transition-colors"
                title={t('msg.close')}
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {/* 🔒 sandbox="" → no scripts, no same-origin: untrusted HTML rendered fully isolated. */}
            <iframe
              title={t('msg.html_preview')}
              srcDoc={html}
              sandbox=""
              className="flex-1 w-full bg-white"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function ProseBody({ text, className, indent, streaming, hasMessageActions }: { text: string; className?: string; indent: boolean; streaming: boolean; hasMessageActions: boolean }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  // While streaming, never clamp or show the action row — the text is still growing and
  // collapsing mid-stream causes flicker (compute these only once the message is complete).
  const isLong = !streaming && text.length > LONG_CHARS;
  // Downloads belong ONLY to the long-output collapse box: "boxed ⇔ downloadable" is one
  // rule (isLong). Short/normal replies get no .md/.html affordance — the persistent
  // message action row (👍 👎 copy 重新生成 / refine) is the parent's and stays on every message.
  const showDownloads = isLong;
  // Standalone copy keeps its old, lower threshold — but only when the parent renders no
  // message action row (which owns copy otherwise; see hasMessageActions).
  const showCopy = !streaming && !hasMessageActions && text.length >= COPY_MIN_CHARS;
  const ind = indent ? 'ml-5' : '';

  const copy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }, [text]);

  const downloadHtml = useCallback(() => {
    const root = ref.current?.querySelector('[data-md-root]');
    let inner = root?.innerHTML ?? '';
    // Mirror the .md export heuristic on the rendered DOM: when the text-level rule
    // says "strip the preamble", drop everything before the first rendered h1–h3.
    if (root && exportMarkdown(text) !== text) {
      const clone = root.cloneNode(true) as HTMLElement;
      const heading = clone.querySelector('h1, h2, h3');
      if (heading) {
        for (let node: Element | null = heading; node && node !== clone; node = node.parentElement) {
          while (node.previousSibling) node.previousSibling.remove();
        }
        inner = clone.innerHTML;
      }
    }
    triggerDownload(`message-${Date.now()}.html`, buildStandaloneHtml(inner, 'Arslan export'), 'text/html;charset=utf-8');
  }, [text]);

  const collapsed = isLong && !expanded;

  return (
    <div>
      <div
        ref={ref}
        style={collapsed ? { position: 'relative', maxHeight: CLAMP_PX, overflow: 'hidden' } : { position: 'relative' }}
      >
        <div data-md-root>
          <Markdown className={className}>{text}</Markdown>
        </div>
        {collapsed && (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-20"
            style={{ background: 'linear-gradient(to bottom, transparent, var(--color-background))' }}
          />
        )}
      </div>

      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className={`${ind} mt-1 flex items-center gap-1 text-[10.5px] font-mono text-primary hover:underline`}
        >
          {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          {expanded ? t('msg.collapse') : t('msg.expand')}
        </button>
      )}

      {(showCopy || showDownloads) && (
        <div className={`${ind} mt-1.5 flex items-center gap-0.5 text-[10px] font-mono opacity-70 hover:opacity-100 transition-opacity`}>
          {/* Copy lives in the persistent message action row (👍 👎 copy 重新生成) when the parent
              renders one (spawn deliverables); non-deliverable messages have no message row,
              so copy stays here (showCopy). */}
          {showCopy && (
            <ActionButton onClick={copy} title={t('msg.copy')}>
              {copied ? <Check className="w-3 h-3 text-success" /> : <Copy className="w-3 h-3" />}
              {copied ? t('msg.copied') : t('msg.copy')}
            </ActionButton>
          )}
          {/* Downloads live with the collapse box (like code blocks own their copy button):
              rendered iff the message is long enough to be boxed (showDownloads === isLong). */}
          {showDownloads && (
            <>
              <ActionButton
                onClick={() => triggerDownload(`message-${Date.now()}.md`, exportMarkdown(text), 'text/markdown;charset=utf-8')}
                title={t('msg.download_md')}
              >
                <Download className="w-3 h-3" /> .md
              </ActionButton>
              <ActionButton onClick={downloadHtml} title={t('msg.download_html')}>
                <Download className="w-3 h-3" /> .html
              </ActionButton>
            </>
          )}
        </div>
      )}
    </div>
  );
}

interface Props {
  text: string;
  className?: string;
  /** When true, indent the card / action-row to align with a pl-5 markdown body (linear layout). */
  indent?: boolean;
  /** True while the message is still streaming — suppresses collapse/export/HTML-card until done. */
  streaming?: boolean;
  /** True when the parent renders a persistent message action row (👍 👎 copy 重新生成) below this
   *  message — the prose export row then omits its own copy button to avoid a duplicate. */
  hasMessageActions?: boolean;
}

export default function MessageBody({ text, className, indent = false, streaming = false, hasMessageActions = false }: Props) {
  if (!streaming && isFullHtmlDoc(text)) {
    // A bare doc that starts with the doctype but lost its </html> to max-tokens is
    // still shown as a card — honestly labeled truncated.
    return <HtmlDocCard html={text} indent={indent} hasMessageActions={hasMessageActions}
                        truncated={!/<\/html>/i.test(text)} />;
  }
  // Embedded doc (preamble/fence despite the skill contract) → salvage: short intro as
  // prose, the document as the preview/download card. 🔒 The card srcdoc comes only from
  // the extracted block of THIS message's text — same trust boundary as the bare case.
  if (!streaming) {
    const embedded = extractEmbeddedHtmlDoc(text);
    if (embedded) {
      return (
        <div className="space-y-2">
          {embedded.pre && (
            <ProseBody text={embedded.pre} className={className} indent={indent}
                       streaming={false} hasMessageActions={true} />
          )}
          <HtmlDocCard html={embedded.html} indent={indent} hasMessageActions={hasMessageActions}
                       truncated={embedded.truncated} />
        </div>
      );
    }
  }
  return <ProseBody text={text} className={className} indent={indent} streaming={streaming} hasMessageActions={hasMessageActions} />;
}
