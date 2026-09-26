import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { createBackup, shellAvailable } from '../../lib/shell';

export default function CreateBackupButton() {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  if (!shellAvailable()) return null;
  return <div>
    <button type="button" disabled={busy} className="px-3 py-2 border border-border rounded-lg text-sm"
      onClick={async () => {
        setBusy(true); setFailed(false);
        try { setFailed(!await createBackup()); } finally { setBusy(false); }
      }}>{t('workspace.createBackup')}</button>
    {failed && <p role="alert">{t('workspace.backupUnavailable')}</p>}
  </div>;
}
