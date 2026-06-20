/**
 * Premium markdown renderer for Arslan chat messages.
 * Uses react-markdown + remark-gfm (GFM: tables, task-lists, strikethrough, autolinks).
 * No rehype-raw — arbitrary HTML from LLM output is NOT rendered.
 * Streaming-safe: partial/incomplete markdown degrades gracefully.
 */
import React, { useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Copy, Check, Info, Lightbulb, AlertTriangle, AlertCircle, Flame } from 'lucide-react';

// ─── GFM Alert parsing ────────────────────────────────────────────────────────
// remark-gfm 4.x does NOT parse GitHub-style alerts ([!NOTE] etc.) natively.
// We detect them inside blockquote children and transform them into a richer node.

const ALERT_TYPES = {
  NOTE: {
    Icon: Info,
    label: 'Note',
    colorClass: 'text-sky-400',
    bgClass: 'bg-sky-950/30',
    borderClass: 'border-sky-500/50',
    titleClass: 'text-sky-400',
  },
  TIP: {
    Icon: Lightbulb,
    label: 'Tip',
    colorClass: 'text-emerald-400',
    bgClass: 'bg-emerald-950/30',
    borderClass: 'border-emerald-500/50',
    titleClass: 'text-emerald-400',
  },
  WARNING: {
    Icon: AlertTriangle,
    label: 'Warning',
    colorClass: 'text-amber-400',
    bgClass: 'bg-amber-950/30',
    borderClass: 'border-amber-500/50',
    titleClass: 'text-amber-400',
  },
  IMPORTANT: {
    Icon: AlertCircle,
    label: 'Important',
    colorClass: 'text-violet-400',
    bgClass: 'bg-violet-950/30',
    borderClass: 'border-violet-500/50',
    titleClass: 'text-violet-400',
  },
  CAUTION: {
    Icon: Flame,
    label: 'Caution',
    colorClass: 'text-red-400',
    bgClass: 'bg-red-950/30',
    borderClass: 'border-red-500/50',
    titleClass: 'text-red-400',
  },
} as const;

type AlertType = keyof typeof ALERT_TYPES;

// Extract text from react children recursively (for alert type detection)
function extractText(children: React.ReactNode): string {
  if (typeof children === 'string') return children;
  if (Array.isArray(children)) return children.map(extractText).join('');
  if (React.isValidElement(children) && children.props) {
    return extractText((children.props as { children?: React.ReactNode }).children);
  }
  return '';
}

function detectAlertType(children: React.ReactNode): AlertType | null {
  const text = extractText(children).trimStart();
  const match = text.match(/^\[!(NOTE|TIP|WARNING|IMPORTANT|CAUTION)\]/i);
  if (match) return match[1].toUpperCase() as AlertType;
  return null;
}

// Strip the [!TYPE] prefix from the first text node in children
function stripAlertPrefix(children: React.ReactNode): React.ReactNode {
  if (typeof children === 'string') {
    return children.replace(/^\s*\[!(NOTE|TIP|WARNING|IMPORTANT|CAUTION)\]\n?/i, '').trimStart();
  }
  if (Array.isArray(children)) {
    const [first, ...rest] = children;
    const stripped = stripAlertPrefix(first);
    if (stripped === '' || stripped === null) return rest;
    return [stripped, ...rest];
  }
  if (React.isValidElement<{ children?: React.ReactNode }>(children)) {
    const props = children.props;
    const newChildren = stripAlertPrefix(props.children);
    return React.cloneElement(children, { children: newChildren });
  }
  return children;
}

// ─── Copy button for code blocks ──────────────────────────────────────────────

function CopyButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [code]);

  return (
    <button
      onClick={handleCopy}
      title="Copy code"
      style={{
        position: 'absolute',
        top: '8px',
        right: '8px',
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        padding: '3px 8px',
        borderRadius: '5px',
        fontSize: '10px',
        fontFamily: 'var(--font-mono, "JetBrains Mono", monospace)',
        background: copied ? 'rgba(255,142,36,0.15)' : 'rgba(255,255,255,0.05)',
        border: `1px solid ${copied ? 'rgba(255,142,36,0.5)' : 'rgba(255,255,255,0.08)'}`,
        color: copied ? '#FF8E24' : '#9ca3af',
        cursor: 'pointer',
        transition: 'all 0.15s ease',
        lineHeight: 1,
      }}
    >
      {copied ? <Check size={11} /> : <Copy size={11} />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

// ─── Markdown component overrides ─────────────────────────────────────────────

const components: import('react-markdown').Components = {
  // Headings
  h1: ({ children }) => (
    <h1 style={{
      fontSize: '1.35em',
      fontWeight: 700,
      letterSpacing: '-0.02em',
      color: 'var(--md-heading, #f1f5f9)',
      marginTop: '1.4em',
      marginBottom: '0.6em',
      paddingBottom: '0.35em',
      borderBottom: '1px solid rgba(255,142,36,0.2)',
      lineHeight: 1.25,
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
    }}>
      <span style={{ display: 'inline-block', width: '3px', height: '1.1em', background: '#FF8E24', borderRadius: '2px', flexShrink: 0, marginTop: '1px' }} />
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 style={{
      fontSize: '1.15em',
      fontWeight: 700,
      letterSpacing: '-0.015em',
      color: 'var(--md-heading, #e2e8f0)',
      marginTop: '1.2em',
      marginBottom: '0.5em',
      paddingBottom: '0.3em',
      borderBottom: '1px solid rgba(30,35,48,0.9)',
      lineHeight: 1.3,
      display: 'flex',
      alignItems: 'center',
      gap: '7px',
    }}>
      <span style={{ display: 'inline-block', width: '2.5px', height: '1em', background: 'rgba(255,142,36,0.7)', borderRadius: '2px', flexShrink: 0 }} />
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 style={{
      fontSize: '1.02em',
      fontWeight: 600,
      letterSpacing: '-0.01em',
      color: 'var(--md-heading, #cbd5e1)',
      marginTop: '1em',
      marginBottom: '0.4em',
      lineHeight: 1.35,
    }}>
      {children}
    </h3>
  ),
  h4: ({ children }) => (
    <h4 style={{
      fontSize: '0.93em',
      fontWeight: 600,
      color: 'var(--md-heading, #94a3b8)',
      marginTop: '0.9em',
      marginBottom: '0.3em',
      textTransform: 'uppercase',
      letterSpacing: '0.04em',
      lineHeight: 1.35,
    }}>
      {children}
    </h4>
  ),

  // Paragraph
  p: ({ children }) => (
    <p style={{
      margin: '0.7em 0',
      lineHeight: 1.65,
      color: 'inherit',
    }}>
      {children}
    </p>
  ),

  // Inline formatting
  strong: ({ children }) => (
    <strong style={{
      fontWeight: 700,
      color: 'var(--md-strong, #f8fafc)',
    }}>
      {children}
    </strong>
  ),
  em: ({ children }) => (
    <em style={{
      fontStyle: 'italic',
      color: 'var(--md-em, #cbd5e1)',
    }}>
      {children}
    </em>
  ),
  del: ({ children }) => (
    <del style={{
      textDecoration: 'line-through',
      color: '#64748b',
      opacity: 0.85,
    }}>
      {children}
    </del>
  ),

  // Inline code
  code: ({ children, className }) => {
    // Block code is handled by `pre` below; inline code has no className
    const isBlock = Boolean(className);
    if (isBlock) {
      return <code className={className}>{children}</code>;
    }
    return (
      <code style={{
        fontFamily: '"JetBrains Mono", "Fira Mono", monospace',
        fontSize: '0.84em',
        background: 'rgba(26,30,43,0.9)',
        border: '1px solid rgba(35,41,62,0.9)',
        borderRadius: '4px',
        padding: '1.5px 5px',
        color: '#e2a86d',
        letterSpacing: '-0.01em',
      }}>
        {children}
      </code>
    );
  },

  // Code blocks
  pre: ({ children }) => {
    // Extract lang and raw code from children
    let lang = '';
    let rawCode = '';
    if (React.isValidElement(children)) {
      const codeEl = children as React.ReactElement<{ className?: string; children?: React.ReactNode }>;
      const cls = codeEl.props?.className || '';
      const match = cls.match(/language-(\S+)/);
      if (match) lang = match[1];
      rawCode = extractText(codeEl.props?.children);
    }

    return (
      <div style={{
        position: 'relative',
        margin: '1em 0',
        borderRadius: '10px',
        border: '1px solid rgba(35,41,62,0.95)',
        background: '#0d1017',
        overflow: 'hidden',
      }}>
        {/* Header bar */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '6px 12px',
          background: 'rgba(255,255,255,0.02)',
          borderBottom: '1px solid rgba(35,41,62,0.8)',
          minHeight: '30px',
        }}>
          {lang ? (
            <span style={{
              fontFamily: '"JetBrains Mono", monospace',
              fontSize: '10px',
              color: '#FF8E24',
              opacity: 0.85,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
            }}>
              {lang}
            </span>
          ) : (
            <span style={{ fontSize: '10px', color: '#4b5563' }}>code</span>
          )}
          <CopyButton code={rawCode} />
        </div>
        {/* Code body */}
        <pre style={{
          margin: 0,
          padding: '14px 16px',
          overflowX: 'auto',
          fontFamily: '"JetBrains Mono", "Fira Mono", monospace',
          fontSize: '12px',
          lineHeight: 1.6,
          color: '#c9d1d9',
          whiteSpace: 'pre',
          WebkitOverflowScrolling: 'touch',
        }}>
          {children}
        </pre>
      </div>
    );
  },

  // Links
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        color: '#FF8E24',
        textDecoration: 'none',
        borderBottom: '1px solid transparent',
        transition: 'border-color 0.15s',
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderBottomColor = '#FF8E24'; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderBottomColor = 'transparent'; }}
    >
      {children}
    </a>
  ),

  // Unordered lists
  ul: ({ children }) => (
    <ul style={{
      margin: '0.6em 0',
      paddingLeft: '1.35em',
      listStyle: 'none',
      display: 'flex',
      flexDirection: 'column',
      gap: '0.3em',
    }}>
      {children}
    </ul>
  ),

  // Ordered lists
  ol: ({ children }) => (
    <ol style={{
      margin: '0.6em 0',
      paddingLeft: '1.6em',
      listStyleType: 'decimal',
      display: 'flex',
      flexDirection: 'column',
      gap: '0.3em',
      color: 'inherit',
    }}>
      {children}
    </ol>
  ),

  // List items — handles task list checkboxes
  li: ({ children, className }) => {
    const isTask = className === 'task-list-item';
    // For task lists, react-markdown injects an <input type="checkbox"> as first child
    return (
      <li style={{
        position: 'relative',
        paddingLeft: isTask ? '0' : '1.1em',
        color: 'inherit',
        lineHeight: 1.6,
        listStyle: isTask ? 'none' : 'inherit',
      }}>
        {!isTask && (
          <span style={{
            position: 'absolute',
            left: 0,
            top: '0.55em',
            width: '5px',
            height: '5px',
            borderRadius: '50%',
            background: 'rgba(255,142,36,0.7)',
            flexShrink: 0,
          }} />
        )}
        {children}
      </li>
    );
  },

  // Task-list checkboxes
  input: ({ type, checked }) => {
    if (type === 'checkbox') {
      return (
        <input
          type="checkbox"
          checked={checked}
          readOnly
          style={{
            accentColor: '#FF8E24',
            marginRight: '6px',
            verticalAlign: 'middle',
            cursor: 'default',
            width: '12px',
            height: '12px',
            borderRadius: '3px',
          }}
        />
      );
    }
    return <input type={type} />;
  },

  // Blockquotes — detect GFM alerts, else premium callout
  blockquote: ({ children }) => {
    const alertType = detectAlertType(children);
    if (alertType && ALERT_TYPES[alertType]) {
      const { Icon, label, bgClass, borderClass, titleClass } = ALERT_TYPES[alertType];
      const stripped = stripAlertPrefix(children);
      return (
        <div className={`${bgClass} ${borderClass}`} style={{
          border: `1px solid`,
          borderLeft: '3px solid',
          borderRadius: '8px',
          padding: '12px 16px',
          margin: '0.85em 0',
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '7px',
            marginBottom: '8px',
          }}>
            <Icon size={14} className={titleClass} style={{ flexShrink: 0 }} />
            <span className={titleClass} style={{ fontWeight: 700, fontSize: '11px', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              {label}
            </span>
          </div>
          <div style={{ color: '#cbd5e1', lineHeight: 1.6, fontSize: '0.95em' }}>
            {stripped}
          </div>
        </div>
      );
    }

    // Regular blockquote — premium amber-border callout
    return (
      <blockquote style={{
        borderLeft: '3px solid #FF8E24',
        background: 'rgba(255,142,36,0.05)',
        borderRadius: '0 8px 8px 0',
        margin: '0.85em 0',
        padding: '10px 16px',
        color: '#94a3b8',
        fontStyle: 'italic',
      }}>
        {children}
      </blockquote>
    );
  },

  // Tables with horizontal scroll
  table: ({ children }) => (
    <div style={{ overflowX: 'auto', margin: '1em 0', borderRadius: '8px', border: '1px solid rgba(35,41,62,0.9)' }}>
      <table style={{
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: '0.9em',
        fontFamily: 'inherit',
        minWidth: '400px',
      }}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => (
    <thead style={{ background: 'rgba(255,142,36,0.07)', borderBottom: '1px solid rgba(35,41,62,0.95)' }}>
      {children}
    </thead>
  ),
  tbody: ({ children }) => (
    <tbody>{children}</tbody>
  ),
  tr: ({ children }) => (
    <tr style={{ borderBottom: '1px solid rgba(30,35,48,0.7)' }}>
      {children}
    </tr>
  ),
  th: ({ children }) => (
    <th style={{
      padding: '8px 14px',
      textAlign: 'left',
      color: '#FF8E24',
      fontWeight: 600,
      fontSize: '0.85em',
      letterSpacing: '0.04em',
      textTransform: 'uppercase',
      whiteSpace: 'nowrap',
    }}>
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td style={{
      padding: '8px 14px',
      color: '#cbd5e1',
      verticalAlign: 'top',
      lineHeight: 1.5,
    }}>
      {children}
    </td>
  ),

  // Horizontal rule
  hr: () => (
    <hr style={{
      border: 'none',
      borderTop: '1px solid rgba(30,35,48,0.9)',
      margin: '1.4em 0',
    }} />
  ),

  // Images
  img: ({ src, alt }) => (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      style={{
        maxWidth: '100%',
        borderRadius: '8px',
        display: 'block',
        margin: '0.8em 0',
      }}
    />
  ),
};

// ─── Public API ───────────────────────────────────────────────────────────────

interface MarkdownProps {
  children: string;
  /** Extra class on the wrapper div */
  className?: string;
}

export default function Markdown({ children, className = '' }: MarkdownProps) {
  return (
    <div
      className={className}
      style={{
        // Cascade color tokens so overrides like .light-theme work via CSS vars
        '--md-heading': 'inherit',
        '--md-strong': 'inherit',
        '--md-em': 'inherit',
      } as React.CSSProperties}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
