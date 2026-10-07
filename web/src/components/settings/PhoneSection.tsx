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
import type { PhoneCode, PhoneDevice, PhoneRequest, PhoneStatus } from "../../api/client.types";
import { formatRelativeTime } from "./relativeTime";

const EMPTY: PhoneStatus = { connected: false, bridge: {}, devices: [], pending: [], code: null };
/** How long an allowed phone shows as Connecting… before the Bridge's own list must take over. */
const ACCEPTED_GRACE_MS = 15_000;

export default function PhoneSection({ pollMs = 3000, enabled = false, onEnabledChange }: {
  pollMs?: number;
  /** "Use Arslan from your iPhone": the desktop shell runs the Bridge only while this is on. */
  enabled?: boolean;
  onEnabledChange?: (value: boolean) => void;
}) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<PhoneStatus>(EMPTY);
  const [code, setCode] = useState<PhoneCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  // Phones just allowed here, shown as Connecting… until the Bridge's list names them (a poll later).
  const [accepted, setAccepted] = useState<{ request: PhoneRequest; at: number }[]>([]);

  const load = async () => {
    try { setStatus(await api.phoneStatus()); } catch { setStatus(EMPTY); }
  };
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), pollMs);   // a request can arrive any time
    return () => clearInterval(timer);
  }, [pollMs]);

  const listed = new Set(status.devices.map(d => d.device_id));
  const waiting: PhoneDevice[] = accepted
    .filter(({ request, at }) => request.phone_id && !listed.has(request.phone_id) && Date.now() - at < ACCEPTED_GRACE_MS)
    .map(({ request }) => ({ device_id: request.phone_id!, name: request.phone_name || "iPhone", state: "connecting" }));
  const devices = [...status.devices, ...waiting];

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
      {/* 0.1.53: the iPhone app is not on the App Store yet; shown as a teaser (user, 2026-10-05). The
          switch stays usable. Remove this when the app is out (its pairing QR becomes a link then). */}
      <div data-testid="phone-coming-soon" className="flex items-start gap-2 rounded-xl border border-primary/30 bg-primary/5 p-3 max-w-xl">
        <span className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-[10px] font-semibold text-primary-foreground">{t("settings.phoneComingSoon")}</span>
        <p className="text-[11px] text-muted-foreground">{t("settings.phoneComingSoonDesc")}</p>
      </div>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h4 className="text-xs font-bold text-foreground">{t("settings.phoneEnable")}</h4>
          <p className="text-[11px] text-muted-foreground mt-0.5 max-w-xl">{t("settings.phoneEnableDesc")}</p>
        </div>
        <input id="settings-phone-enabled" data-testid="settings-phone-enabled" type="checkbox" checked={enabled}
          onChange={(e) => onEnabledChange?.(e.target.checked)}
          className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 cursor-pointer" />
      </div>

      {enabled && !status.connected && <p data-testid="phone-offline" className="text-xs text-muted-foreground">{t("settings.phoneBridgeOffline")}</p>}

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
          onClick={() => void act(async () => {
            await api.phoneDecide(request.request_id, true);
            setAccepted(list => [...list, { request, at: Date.now() }]);
          })}>{t("settings.phoneAccept")}</button>
        <button type="button" className="rounded-lg border border-border px-3 py-1 text-xs disabled:opacity-50" disabled={busy}
          onClick={() => void act(() => api.phoneDecide(request.request_id, false))}>{t("settings.phoneDecline")}</button>
      </div>)}

      <div className="space-y-2">
        <h4 className="text-xs font-bold text-foreground">{t("settings.phoneDevices")}</h4>
        {!devices.length && <p className="text-[11px] text-muted-foreground">{t("settings.phoneNone")}</p>}
        {devices.map(device => <div key={device.device_id} data-testid={`phone-device-${device.device_id}`}
          className="flex items-center gap-3 rounded-lg bg-foreground/5 px-3 py-2 text-sm">
          <span className="flex-1">{device.name}</span>
          <DeviceState device={device} />
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

/** "Connecting…" until the Bridge has read a message from the phone, then "Connected · last seen …"
 *  (mobile-bridge-protocol §3.3). An older Bridge sends no state, and nothing is shown. */
function DeviceState({ device }: { device: PhoneDevice }) {
  const { t } = useTranslation();
  if (device.state !== "connecting" && device.state !== "connected") return null;
  const connected = device.state === "connected";
  return (
    <span data-testid={`phone-device-state-${device.device_id}`} data-state={device.state}
      className="flex items-center gap-1.5 text-[11px] text-muted-foreground whitespace-nowrap">
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-success" : "bg-warning animate-pulse"}`} />
      {!connected ? t("settings.phoneConnecting")
        : device.last_seen ? t("settings.phoneConnectedSeen", { when: formatRelativeTime(device.last_seen, t) })
        : t("settings.phoneConnected")}
    </span>
  );
}
