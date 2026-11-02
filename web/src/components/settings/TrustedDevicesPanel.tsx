import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { request } from '../../api/client';
import type { TrustedDevice } from '../../types';

type Props = {
  devices: TrustedDevice[];
  onChange: (devices: TrustedDevice[]) => void;
};

/**
 * SBX-6a (the user, 2026-11-02: 「选 c」): the local-network devices sandboxed commands may reach through Arslan's
 * proxy. One device at a time, never a range: the backend looks a name up once and pins it to the address it has
 * now (POST /settings/trusted-devices/resolve), and refuses public, loopback, link-local and this Mac's own
 * addresses, saying why. The list is saved as the setting `sandbox_trusted_devices`.
 */
export default function TrustedDevicesPanel({ devices, onChange }: Props) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = async () => {
    const host = draft.trim();
    if (!host || busy) return;
    setBusy(true);
    setError(null);
    try {
      const entry = await request<TrustedDevice>('/settings/trusted-devices/resolve', {
        method: 'POST', body: JSON.stringify({ host }),
      });
      if (!devices.some((d) => d.address === entry.address && d.host === entry.host)) {
        onChange([...devices, entry]);
      }
      setDraft('');
    } catch (exc) {
      const code = (exc as { detail?: { code?: string } })?.detail?.code;
      setError(t(`settings.trustedDevicesRefused_${code ?? 'unresolvable'}`,
        { defaultValue: t('settings.trustedDevicesRefused_unresolvable') }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pl-4 border-l-2 border-primary/20 space-y-2" data-testid="trusted-devices">
      <div>
        <h4 className="text-[13px] font-medium text-foreground">{t('settings.trustedDevicesTitle')}</h4>
        <p className="text-[12px] leading-snug text-muted-foreground mt-0.5 max-w-xl">{t('settings.trustedDevicesDesc')}</p>
      </div>
      {devices.length === 0 ? (
        <p className="text-[11px] text-muted-foreground font-sans">{t('settings.trustedDevicesEmpty')}</p>
      ) : (
        <ul className="space-y-1">
          {devices.map((d) => (
            <li key={`${d.host ?? ''}@${d.address}`} className="flex items-center justify-between gap-3 text-[12px]">
              <span className="min-w-0">
                <span className="text-foreground">{d.host ?? d.address}</span>
                <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                  {d.host ? d.address : t('settings.trustedDevicesAddressOnly')}
                </span>
              </span>
              <button type="button" data-testid={`trusted-device-remove-${d.address}`}
                onClick={() => onChange(devices.filter((x) => x !== d))}
                className="shrink-0 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground">
                {t('settings.trustedDevicesRemove')}
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="flex items-end gap-2 max-w-xl" onSubmit={(e) => { e.preventDefault(); void add(); }}>
        <label className="flex flex-col gap-1 grow text-[12px] text-muted-foreground">
          {t('settings.trustedDevicesAddLabel')}
          <input type="text" value={draft} onChange={(e) => setDraft(e.target.value)} data-testid="trusted-device-input"
            placeholder={t('settings.trustedDevicesAddPlaceholder')} maxLength={253}
            className="h-8 rounded-md border border-border bg-background px-2 text-[13px] text-foreground" />
        </label>
        <button type="submit" disabled={busy || !draft.trim()} data-testid="trusted-device-add"
          className="h-8 rounded-md bg-primary px-3 text-[12px] font-medium text-primary-foreground disabled:opacity-50">
          {t('settings.trustedDevicesAdd')}
        </button>
      </form>
      {error && <p className="text-[11px] text-danger" role="alert" data-testid="trusted-device-error">{error}</p>}
      <p className="text-[11px] text-muted-foreground font-sans max-w-xl">{t('settings.trustedDevicesNote')}</p>
    </div>
  );
}
