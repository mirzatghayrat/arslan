import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Check } from 'lucide-react';

/**
 * CopyButton — copies `text` to the clipboard with a brief "copied" confirmation.
 * A message-level action primitive: it copies the whole message text and is meant to
 * live in the persistent message action row (👍 👎 copy 重新生成), distinct from a
 * content card's own copy button (e.g. the HTML-doc card / a code block), which copies
 * that artifact. Styling is fully delegated via `className` so each chat layout
 * (quartz / brutalist / linear) can match its own action row.
 */
export default function CopyButton({
  text,
  className = '',
  showLabel = false,
}: {
  text: string;
  className?: string;
  showLabel?: boolean;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const copy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }, [text]);

  return (
    <button type="button" onClick={copy} title={t('msg.copy')} className={className}>
      {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
      {showLabel && <span>{copied ? t('msg.copied') : t('msg.copy')}</span>}
    </button>
  );
}
