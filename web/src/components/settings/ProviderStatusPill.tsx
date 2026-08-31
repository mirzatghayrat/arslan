/**
 * One provider's status, said in words rather than implied by a colour.
 *
 * There used to be a bare coloured dot whose green meant "the model-list
 * endpoint answered" — a fact that is true of a public model list with no key
 * at all. A dot cannot carry that caveat, so it read as "this works" and was
 * wrong exactly when it mattered. The pill says what it knows, and "not tested"
 * is a state it is allowed to be in rather than something dressed as working.
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import type { ProviderStatus } from '../../lib/providerStatus';

const STYLES: Record<ProviderStatus, string> = {
  ok: 'bg-success/10 text-success border-success/30',
  failed: 'bg-danger/10 text-danger border-danger/30',
  untested: 'bg-surface-raised text-subtle-foreground border-border',
  testing: 'bg-surface-raised text-muted-foreground border-border',
};

const LABEL_KEYS: Record<ProviderStatus, string> = {
  ok: 'settings.statusOk',
  failed: 'settings.statusFailed',
  untested: 'settings.statusUntested',
  testing: 'settings.statusTesting',
};

export default function ProviderStatusPill({
  status,
  testId,
}: {
  status: ProviderStatus;
  testId?: string;
}) {
  const { t } = useTranslation();
  return (
    <span
      data-testid={testId}
      data-status={status}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-mono font-medium whitespace-nowrap ${STYLES[status]}`}
    >
      {status === 'testing' ? (
        <Loader2 className="w-2.5 h-2.5 animate-spin" />
      ) : (
        <span aria-hidden="true">{status === 'untested' ? '○' : '●'}</span>
      )}
      {t(LABEL_KEYS[status])}
    </span>
  );
}
