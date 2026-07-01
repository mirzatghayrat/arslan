/**
 * MessageBody — wraps assistant/spawn message text with long-output handling:
 *   1. Full-HTML documents (`<!DOCTYPE html>…`) render as a compact card + sandboxed
 *      preview instead of an escaped wall (Markdown.tsx deliberately omits rehype-raw).
 *   2. Long prose collapses in-bubble (max-height clamp + fade + Show more / 收起).
 *   3. A subtle per-message action row: Copy (raw markdown) + Download .md / .html.
 *
 * 🔒 SECURITY: the HTML preview is a fully sandboxed <iframe srcDoc> with NO sandbox
 * flags (no scripts, no same-origin) — untrusted model HTML is rendered isolated and
 * can never reach the app DOM or our origin. Never relax this to allow-same-origin.
 */
import React, { useState, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Check, Download, ChevronDown, ChevronUp, Eye, X, FileCode } from 'lucide-react';
import Markdown from './Markdown';

const LONG_CHARS = 1800;      // prose longer than this collapses in-bubble
const EXPORT_MIN_CHARS = 240; // shorter messages don't get an export row (keeps chat clean)
const CLAMP_PX = 360;         // collapsed height

function isFullHtmlDoc(s: string): boolean {
  const t = s.trimStart();
  return /^<!doctype html/i.test(t) || (/^<html[\s>]/i.test(t) && /<\/html>/i.test(s));
}

function triggerDownload(filename: string, content: string, mime: string) {
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

function HtmlDocCard({ html, indent }: { html: string; indent: boolean }) {
  const { t } = useTranslation();
  const [preview, setPreview] = useState(false);
  const [copied, setCopied] = useState(false);
  const kb = Math.max(1, Math.round(html.length / 1024));

  const copy = useCallback(() => {
    navigator.clipboard.writeText(html).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }, [html]);

  return (
    <div className={indent ? 'pl-5' : ''}>
      <div className="flex items-center gap-2.5 max-w-md border border-border-strong bg-background/60 rounded-lg px-3 py-2.5">
        <FileCode className="w-4 h-4 text-primary shrink-0" />
        <span className="text-[11.5px] text-foreground font-medium flex-1">
          {t('msg.html_doc', { kb })}
        </span>
        <div className="flex items-center gap-0.5 text-[10.5px] font-mono">
          <ActionButton onClick={() => setPreview(true)} title={t('msg.preview')}>
            <Eye className="w-3 h-3" /> {t('msg.preview')}
          </ActionButton>
          <ActionButton onClick={copy} title={t('msg.copy')}>
            {copied ? <Check className="w-3 h-3 text-success" /> : <Copy className="w-3 h-3" />}
          </ActionButton>
          <ActionButton
            onClick={() => triggerDownload(`document-${Date.now()}.html`, html, 'text/html;charset=utf-8')}
            title={t('msg.download_html')}
          >
            <Download className="w-3 h-3" /> .html
          </ActionButton>
        </div>
      </div>

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
  const showExport = !streaming && text.length >= EXPORT_MIN_CHARS;
  const ind = indent ? 'ml-5' : '';

  const copy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }, [text]);

  const downloadHtml = useCallback(() => {
    const inner = ref.current?.querySelector('[data-md-root]')?.innerHTML ?? '';
    triggerDownload(`message-${Date.now()}.html`, buildStandaloneHtml(inner, 'Arslan export'), 'text/html;charset=utf-8');
  }, []);

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

      {showExport && (
        <div className={`${ind} mt-1.5 flex items-center gap-0.5 text-[10px] font-mono opacity-70 hover:opacity-100 transition-opacity`}>
          {/* Copy lives in the persistent message action row (👍 👎 copy 重新生成) when the parent
              renders one (spawn deliverables); here we keep only the export buttons to avoid a
              duplicate copy. Non-deliverable messages have no message row, so copy stays. */}
          {!hasMessageActions && (
            <ActionButton onClick={copy} title={t('msg.copy')}>
              {copied ? <Check className="w-3 h-3 text-success" /> : <Copy className="w-3 h-3" />}
              {copied ? t('msg.copied') : t('msg.copy')}
            </ActionButton>
          )}
          <ActionButton
            onClick={() => triggerDownload(`message-${Date.now()}.md`, text, 'text/markdown;charset=utf-8')}
            title={t('msg.download_md')}
          >
            <Download className="w-3 h-3" /> .md
          </ActionButton>
          <ActionButton onClick={downloadHtml} title={t('msg.download_html')}>
            <Download className="w-3 h-3" /> .html
          </ActionButton>
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
    return <HtmlDocCard html={text} indent={indent} />;
  }
  return <ProseBody text={text} className={className} indent={indent} streaming={streaming} hasMessageActions={hasMessageActions} />;
}
