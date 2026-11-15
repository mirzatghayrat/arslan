import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError, request } from '../../api/client';
import { toast } from '../kit';
import { SECTION_ANCHORS } from './sectionRegistry';

type Device = { address: string; host?: string };
/** One row of the list: a device added by name, with every address it was pinned to, or one IP. */
type Row = { key: string; host?: string; addresses: string[] };
type Translate = (key: string, options?: Record<string, unknown>) => string;

function rows(devices: Device[]): Row[] {
  const out: Row[] = [];
  for (const d of devices) {
    const named = d.host ? out.find((r) => r.host === d.host) : undefined;
    if (named) named.addresses.push(d.address);
    else out.push({ key: d.host ?? d.address, ...(d.host ? { host: d.host } : {}), addresses: [d.address] });
  }
  return out;
}

/** What the server said when it refused a device (trusted_devices.Refused), in the user's words. */
export function refusalText(t: Translate, e: unknown, typed: string): string {
  const detail = e instanceof ApiError && e.detail && typeof e.detail === 'object'
    ? e.detail as { code?: string; value?: string } : {};
  const value = detail.value || typed;
  switch (detail.code) {
    case 'not_found': return t('sandboxNet.notFound', { value });
    case 'not_lan': return t('sandboxNet.notLan', { value });
    case 'own_address': return t('sandboxNet.ownAddress');
    case 'listed': return t('sandboxNet.listed');
    default: return t('sandboxNet.failed');
  }
}

interface Props {
  /** "Allow system certificate checks in the sandbox" (default off). */
  systemCertificates: boolean;
  onSystemCertificatesChange?: (value: boolean) => void;
}

/**
 * SBX settings (the mock the user OK'd with A), inside "Run commands in a sandbox": the certificate switch and the
 * trusted local devices. The switch saves through the settings form like its neighbours; the list has its own routes,
 * where the server resolves and checks what is typed. Only the server decides what can be trusted.
 */
export default function SandboxNetworkPanel({ systemCertificates, onSystemCertificatesChange }: Props) {
  const { t } = useTranslation();
  return (
    <>
      {/* The certificate card's deep link (SECTION_ANCHORS.sandbox_certificates) scrolls this row to the top. */}
      <div id={SECTION_ANCHORS.sandbox_certificates.elementId}
        className="scroll-mt-4 flex items-start justify-between gap-4 pl-4 border-l-2 border-primary/20">
        <div>
          <h4 className="text-[13px] font-medium text-foreground">{t('sandboxNet.certificatesTitle')}</h4>
          <p className="text-[12px] leading-snug text-muted-foreground mt-0.5 max-w-xl">{t('sandboxNet.certificatesDesc')}</p>
        </div>
        <input data-testid="settings-sandbox-certificates-toggle" type="checkbox"
          aria-label={t('sandboxNet.certificatesTitle')} checked={systemCertificates}
          onChange={(e) => onSystemCertificatesChange?.(e.target.checked)} className="kit-switch mt-0.5" />
      </div>
      <TrustedDevices />
      <AllowedSites />
    </>
  );
}

/** NET-b: `sandbox_allowed_sites` is one JSON-list string; the server (net_policy.parse_sites) refuses what no list can hold. */
function parseSites(raw: unknown): string[] {
  try {
    const list = typeof raw === 'string' && raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((s): s is string => typeof s === 'string') : [];
  } catch {
    return [];
  }
}

function AllowedSites() {
  const { t } = useTranslation();
  const [sites, setSites] = useState<string[] | null>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  /** The saved list was read: until then a PUT of the whole list would overwrite the saved one with what is shown. */
  const [loaded, setLoaded] = useState(false);
  const [unread, setUnread] = useState(false);

  useEffect(() => {
    let alive = true;
    request<{ sandbox_allowed_sites?: string }>('/settings')
      .then((body) => { if (alive) { setSites(parseSites(body?.sandbox_allowed_sites)); setLoaded(true); } })
      .catch(() => { if (alive) { setSites([]); setUnread(true); } });
    return () => { alive = false; };
  }, []);

  /** Saves the whole list through PUT /settings; the list shown changes only once the server took it. Never before
   * the saved list was read (`loaded`). */
  const save = async (next: string[], typed: string): Promise<boolean> => {
    if (!loaded) return false;
    setBusy(true);
    setError('');
    try {
      await request('/settings', { method: 'PUT', body: JSON.stringify({ sandbox_allowed_sites: JSON.stringify(next) }) });
      setSites(next);
      return true;
    } catch (e) {
      setError(e instanceof ApiError && e.status === 422 ? t('sandboxNet.sitesRefused', { value: typed }) : refusalText(t, e, typed));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    const typed = text.trim().toLowerCase();
    if (!typed || busy || !sites || !loaded) return;
    if (sites.includes(typed)) { setError(t('sandboxNet.listed')); return; }
    if (await save([...sites, typed], typed)) setText('');
  };

  if (sites == null) return null;
  return (
    <div className="pl-4 border-l-2 border-primary/20 space-y-2" data-testid="allowed-sites">
      <div>
        <h4 className="text-[13px] font-medium text-foreground">{t('sandboxNet.sitesTitle')}</h4>
        <p className="text-[12px] leading-snug text-muted-foreground mt-0.5 max-w-xl">{t('sandboxNet.sitesDesc')}</p>
      </div>
      {sites.length === 0 ? (
        <p className="text-[12px] text-subtle-foreground">{t('sandboxNet.sitesEmpty')}</p>
      ) : (
        <ul className="space-y-1">
          {sites.map((site) => (
            <li key={site} data-testid="allowed-site"
              className="flex min-w-0 items-center gap-2.5 rounded-lg border border-border px-2.5 py-1.5 text-[12px]">
              <span className="min-w-0 truncate font-medium text-foreground">{site}</span>
              <span className="flex-1" />
              <button type="button" data-testid={`allowed-site-remove-${site}`} disabled={busy || !loaded}
                onClick={() => void save(sites.filter((s) => s !== site), site)}
                className="shrink-0 text-[12px] text-muted-foreground hover:text-foreground">
                {t('sandboxNet.remove')}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-1.5">
        <input data-testid="allowed-site-input" value={text} autoComplete="off"
          aria-label={t('sandboxNet.sitesInputLabel')} placeholder={t('sandboxNet.sitesPlaceholder')}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void add(); }}
          className="min-w-[180px] flex-1 rounded-lg border border-border-strong bg-surface px-2.5 py-1.5 text-[12px] text-foreground focus:border-primary focus:outline-none" />
        <button type="button" data-testid="allowed-site-add" disabled={busy || !loaded} onClick={() => void add()}
          className="shrink-0 rounded-lg border border-border-strong px-3 py-1.5 text-[12px] text-foreground hover:bg-foreground/5 disabled:opacity-50">
          {t('sandboxNet.sitesAdd')}
        </button>
      </div>
      {(error || unread) && <p role="alert" className="text-[12px] text-danger" data-testid="allowed-site-error">
        {error || t('sandboxNet.failed')}</p>}
    </div>
  );
}

function TrustedDevices() {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    request<{ devices: Device[] }>('/settings/sandbox/trusted-devices')
      .then((body) => { if (alive) setDevices(Array.isArray(body?.devices) ? body.devices : []); })
      .catch(() => { if (alive) setDevices([]); });
    return () => { alive = false; };
  }, []);

  const add = async () => {
    const typed = text.trim().toLowerCase();
    if (!typed || busy) return;
    setBusy(true);
    setError('');
    try {
      const body = await request<{ devices: Device[] }>('/settings/sandbox/trusted-devices',
        { method: 'POST', body: JSON.stringify({ device: typed }) });
      setDevices(body.devices);
      setText('');
      toast(t('sandboxNet.trustedToast', { name: typed }));
    } catch (e) {
      setError(refusalText(t, e, typed));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row: Row) => {
    const query = row.host ? `host=${encodeURIComponent(row.host)}` : `address=${encodeURIComponent(row.addresses[0])}`;
    setError('');
    try {
      const body = await request<{ devices: Device[] }>(`/settings/sandbox/trusted-devices?${query}`, { method: 'DELETE' });
      setDevices(body.devices);
      toast(t('sandboxNet.untrustedToast'));
    } catch {
      setError(t('sandboxNet.failed'));
    }
  };

  if (devices == null) return null;
  const listed = rows(devices);
  return (
    <div className="pl-4 border-l-2 border-primary/20 space-y-2" data-testid="trusted-devices">
      <div>
        <h4 className="text-[13px] font-medium text-foreground">{t('sandboxNet.devicesTitle')}</h4>
        <p className="text-[12px] leading-snug text-muted-foreground mt-0.5 max-w-xl">{t('sandboxNet.devicesDesc')}</p>
      </div>
      {listed.length === 0 ? (
        <p className="text-[12px] text-subtle-foreground" data-testid="trusted-devices-empty">{t('sandboxNet.devicesEmpty')}</p>
      ) : (
        <ul className="space-y-1">
          {listed.map((row) => (
            <li key={row.key} data-testid="trusted-device"
              className="flex min-w-0 items-center gap-2.5 rounded-lg border border-border px-2.5 py-1.5 text-[12px]">
              <span className="min-w-0 truncate font-medium text-foreground">{row.host ?? row.addresses[0]}</span>
              {row.host && <span className="font-mono text-[11.5px] text-muted-foreground">{row.addresses.join(', ')}</span>}
              <span className="flex-1" />
              <button type="button" data-testid={`trusted-device-remove-${row.key}`} onClick={() => void remove(row)}
                className="shrink-0 text-[12px] text-muted-foreground hover:text-foreground">
                {t('sandboxNet.remove')}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-1.5">
        <input data-testid="trusted-device-input" value={text} autoComplete="off"
          aria-label={t('sandboxNet.inputLabel')} placeholder={t('sandboxNet.placeholder')}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void add(); }}
          className="min-w-[180px] flex-1 rounded-lg border border-border-strong bg-surface px-2.5 py-1.5 text-[12px] text-foreground focus:border-primary focus:outline-none" />
        <button type="button" data-testid="trusted-device-add" disabled={busy} onClick={() => void add()}
          className="shrink-0 rounded-lg border border-border-strong px-3 py-1.5 text-[12px] text-foreground hover:bg-foreground/5 disabled:opacity-50">
          {t('sandboxNet.add')}
        </button>
      </div>
      {error && <p role="alert" className="text-[12px] text-danger" data-testid="trusted-device-error">{error}</p>}
    </div>
  );
}
