import { useTranslation } from 'react-i18next';

/** A durable result entry for the host, not just specialist messages. */
export default function HostRunResultButton({ runId, onOpen }: {
  runId?: number | null;
  onOpen: (runId: number) => void;
}) {
  const { t } = useTranslation();
  if (!Number.isSafeInteger(runId) || (runId ?? 0) <= 0) return null;
  return <button type="button" className="msg__replay-btn mt-2"
    onClick={() => onOpen(runId!)}>{t('replay.view_replay')}</button>;
}
