import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { openExternal, shellAvailable } from '../lib/shell';

export default function MarkdownLink({ href, children }: { href?: string; children: ReactNode }) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  return <><a href={href} target="_blank" rel="noopener noreferrer"
    style={{ color: 'var(--color-primary)', textDecoration: 'none', borderBottom: '1px solid transparent' }}
    onMouseEnter={e => { e.currentTarget.style.borderBottomColor = 'var(--color-primary)'; }}
    onMouseLeave={e => { e.currentTarget.style.borderBottomColor = 'transparent'; }}
    onClick={async event => {
      if (!shellAvailable() || !href || (href.startsWith('/') && !href.startsWith('//')) || href.startsWith('#')) return;
      event.preventDefault();
      // The native command independently enforces HTTPS and maintenance gates.
      // Never navigate the privileged WebView to an external document.
      setFailed(!await openExternal(href));
    }}>{children}</a>{failed && <span role="alert" className="ml-2 text-danger">{t('externalLink.failed')}</span>}</>;
}
