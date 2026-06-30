import { useTranslation } from "react-i18next";
import { SpawnAvatar } from "./SpawnAvatar";

interface Props {
  spawnId: number;
  /** Resolved spawn name; falls back to `#<id>` when unknown. */
  spawnName?: string;
  /** One-line capability summary for the proposed spawn. */
  reason: string;
  onConfirm: (spawnId: number) => void;
  onCancel: () => void;
}

/**
 * Inline invite card for a backend `propose_invite` frame. Renders as a compact
 * message-level row below the conversation: the proposed spawn's avatar + name +
 * one-line capability, with Accept / Dismiss. It is NOT a modal/overlay — it reads
 * as the last item in the chat flow.
 *
 * Accept → onConfirm(spawnId) (sends `roster_invite`, backend joins + dispatches the
 * parked task). Dismiss → onCancel() (sends `dismiss_invite`, clears the pending invite).
 */
export default function InviteConfirmCard({ spawnId, spawnName, reason, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const name = spawnName ?? `#${spawnId}`;

  return (
    <div className="invite-inline-card" data-testid="invite-confirm-card">
      <SpawnAvatar seed={name} size={36} className="invite-inline-card__avatar" />
      <div className="invite-inline-card__body">
        <span className="invite-inline-card__name">{name}</span>
        <span className="invite-inline-card__reason">{reason}</span>
      </div>
      <div className="invite-inline-card__actions">
        <button
          type="button"
          className="invite-inline-card__btn invite-inline-card__btn--primary"
          onClick={() => onConfirm(spawnId)}
          data-testid="invite-confirm"
        >
          {t("invite_card.accept")}
        </button>
        <button
          type="button"
          className="invite-inline-card__btn invite-inline-card__btn--ghost"
          onClick={onCancel}
          data-testid="invite-cancel"
        >
          {t("invite_card.dismiss")}
        </button>
      </div>
    </div>
  );
}
