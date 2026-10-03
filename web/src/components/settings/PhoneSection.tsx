/**
 * Settings › iPhone — the iPhone companion (docs/specs/mobile-bridge-protocol.md §6.1).
 *
 * Talking to Arslan from an iPhone goes through the Arslan Bridge (a helper inside Arslan.app)
 * and the user's own iCloud, end-to-end encrypted. This pane shows whether the Bridge is
 * running, makes a one-time pairing code (QR, 10 minutes), and lists requests and paired
 * phones. Accepting a phone happens only here: a click in Arslan's window.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Smartphone, Trash2 } from "lucide-react";
import { api } from "../../api/client";
import type { PhoneCode, PhoneStatus } from "../../api/client.types";

const EMPTY: PhoneStatus = { connected: false, bridge: {}, devices: [], pending: [], code: null };

export default function PhoneSection({ pollMs = 3000 }: { pollMs?: number }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<PhoneStatus>(EMPTY);
  const [code, setCode] = useState<PhoneCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const load = async () => {
    try { setStatus(await api.phoneStatus()); } catch { setStatus(EMPTY); }
  };
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), pollMs);   // a request can arrive any time
    return () => clearInterval(timer);
  }, [pollMs]);

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true); setError(false);
    try { await work(); await load(); } catch { setError(true); } finally { setBusy(false); }
  };

  return (
    <div className="bg-surface border border-border rounded-2xl p-6 space-y-5" data-testid="settings-phone">
      <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
        <Smartphone className="w-4.5 h-4.5 text-primary" />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t("settings.navPhone")}</h3>
      </div>
      <p className="text-[11px] text-muted-foreground max-w-xl">{t("settings.phoneIntro")}</p>

      {!status.connected && <p data-testid="phone-offline" className="text-xs text-muted-foreground">{t("settings.phoneBridgeOffline")}</p>}

      {status.connected && <div className="space-y-3">
        <button type="button" className="rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-foreground/5 disabled:opacity-50"
          disabled={busy} onClick={() => void act(async () => setCode(await api.phoneNewCode()))}>{t("settings.phoneAdd")}</button>
        {code && <div data-testid="phone-code" className="flex items-start gap-4">
          <img src={`data:image/png;base64,${code.qr_png}`} alt={t("settings.phoneScan")} width={180} height={180}
            className="rounded-lg bg-white p-2 [image-rendering:pixelated]" />
          <p className="text-[11px] text-muted-foreground max-w-xs">{t("settings.phoneScan")}</p>
        </div>}
      </div>}

      {status.pending.map(request => <div key={request.request_id} data-testid={`phone-request-${request.request_id}`}
        className="flex flex-wrap items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 p-3 text-sm">
        <span className="flex-1">{t("settings.phoneRequest", { name: request.phone_name || "iPhone" })}</span>
        <button type="button" className="rounded-lg bg-primary px-3 py-1 text-xs text-primary-foreground disabled:opacity-50" disabled={busy}
          onClick={() => void act(() => api.phoneDecide(request.request_id, true))}>{t("settings.phoneAccept")}</button>
        <button type="button" className="rounded-lg border border-border px-3 py-1 text-xs disabled:opacity-50" disabled={busy}
          onClick={() => void act(() => api.phoneDecide(request.request_id, false))}>{t("settings.phoneDecline")}</button>
      </div>)}

      <div className="space-y-2">
        <h4 className="text-xs font-bold text-foreground">{t("settings.phoneDevices")}</h4>
        {!status.devices.length && <p className="text-[11px] text-muted-foreground">{t("settings.phoneNone")}</p>}
        {status.devices.map(device => <div key={device.device_id} data-testid={`phone-device-${device.device_id}`}
          className="flex items-center gap-3 rounded-lg bg-foreground/5 px-3 py-2 text-sm">
          <span className="flex-1">{device.name}</span>
          {device.paired_at && <span className="text-[11px] text-muted-foreground">{t("settings.phonePairedAt", { when: new Date(device.paired_at).toLocaleDateString() })}</span>}
          <button type="button" aria-label={t("settings.phoneRemove")} title={t("settings.phoneRemove")} disabled={busy}
            className="text-muted-foreground hover:text-destructive disabled:opacity-50"
            onClick={() => void act(() => api.phoneRevoke(device.device_id))}><Trash2 size={14} /></button>
        </div>)}
      </div>
      {error && <p role="alert" className="text-xs text-destructive">{t("settings.phoneError")}</p>}
    </div>
  );
}
