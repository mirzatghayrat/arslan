/**
 * SandboxCard — SBX settings (the mock the user OK'd with A): the chat's card for a command the sandbox stopped.
 *
 * - Certificates: the command's certificate check failed with "Allow system certificate checks in the sandbox" off.
 *   "Turn it on in Settings" opens Settings at that switch; nothing is turned on from here.
 * - A device on the local network: "Trust this device" answers THIS card over REST, repeating the device it shows,
 *   and the server pins exactly that (trusted_devices.answer). It's the only way a card trusts anything.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError, request } from '../api/client';
import type { SandboxCardItem } from '../api/client.types';
import { openSection } from '../lib/sections';
import { useArslanStore } from '../stores/arslanStore';
import { Button, toast } from './kit';
import { refusalText } from './settings/SandboxNetworkPanel';

export default function SandboxCard({ card }: { card: SandboxCardItem }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (card.state === 'dismissed') return null;

  const lan = card.kind === 'lan_device';
  const addresses = (card.addresses ?? []).join(', ');
  const device = card.host ? t('sandboxNet.namedDevice', { name: card.host, addresses }) : addresses;
  const path = `/sandbox/cards/${encodeURIComponent(card.cardId)}`;
  const setState = (state: SandboxCardItem['state']) => useArslanStore.getState().setSandboxCardState(card.cardId, state);

  const trust = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await request(path, { method: 'POST',
        body: JSON.stringify({ trust: true, host: card.host ?? null, addresses: card.addresses ?? [] }) });
      setState('trusted');
      toast(t('sandboxNet.trustedToast', { name: device }));
    } catch (e) {
      setError(e instanceof ApiError && (e.status === 404 || e.status === 409) ? t('sandboxNet.cardGone')
        : refusalText(t, e, device));
    } finally {
      setBusy(false);
    }
  };

  const notNow = () => {
    if (lan && card.state === 'open') {
      // The server lets the card go; it would expire unanswered after 30 minutes anyway, so a failure changes nothing.
      void request(path, { method: 'POST', body: JSON.stringify({ trust: false }) }).catch(() => undefined);
    }
    setState('dismissed');
    toast(t('sandboxNet.notNowToast'));
  };

  const title = lan ? t('sandboxNet.lanTitle', { device }) : t('sandboxNet.certificatesCardTitle');
  const body = !lan ? t('sandboxNet.certificatesCardBody')
    : card.state === 'trusted' ? t('sandboxNet.lanTrusted') : t('sandboxNet.lanBody');
  return (
    <div data-testid="sandbox-card" data-kind={card.kind} data-state={card.state}
      className="flex max-w-[560px] flex-col gap-2 rounded-[10px] border border-border border-l-[3px] border-l-ask bg-surface px-3.5 py-3">
      <div className="text-[13px] font-semibold text-foreground" data-testid="sandbox-card-title">{title}</div>
      <p className="text-[12.5px] text-muted-foreground">{body}</p>
      {error && <p role="alert" className="text-[12px] text-danger" data-testid="sandbox-card-error">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {!lan && (
          <Button size="sm" tone="primary" data-testid="sandbox-card-settings"
            onClick={() => openSection('settings', 'sandbox_certificates')}>
            {t('sandboxNet.openSettings')}
          </Button>
        )}
        {lan && card.state === 'open' && (
          <Button size="sm" tone="primary" data-testid="sandbox-card-trust" disabled={busy} onClick={() => void trust()}>
            {t('sandboxNet.trustDevice')}
          </Button>
        )}
        <Button size="sm" tone="secondary" data-testid="sandbox-card-not-now" onClick={notNow}>
          {t('sandboxNet.notNow')}
        </Button>
      </div>
    </div>
  );
}
