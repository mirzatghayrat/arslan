import { useTranslation } from "react-i18next";

interface Props {
  spawnId: number;
  /** Resolved spawn name; falls back to `#<id>` when unknown. */
  spawnName?: string;
  reason: string;
  onConfirm: (spawnId: number) => void;
  onCancel: () => void;
}

/**
 * Confirmation card for a backend `propose_invite` frame. Asks the user to
 * confirm pulling one spawn into the conversation before any roster_invite is
 * sent. 确认 → onConfirm(spawnId); 取消 → onCancel.
 */
export default function InviteConfirmCard({ spawnId, spawnName, reason, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const name = spawnName ?? `#${spawnId}`;

  return (
    <div className="suggest-create-card invite-confirm-card" data-testid="invite-confirm-card">
      <header className="suggest-create-card__head">
        <span className="suggest-create-card__icon" aria-hidden>＋</span>
        <span className="suggest-create-card__title">{t("invite_card.confirm")}</span>
      </header>

      <p className="invite-confirm-card__heading">{t("invite_card.heading", { name, reason })}</p>

      <div className="suggest-create-card__actions">
        <button
          className="suggest-create-card__btn suggest-create-card__btn--primary"
          onClick={() => onConfirm(spawnId)}
          data-testid="invite-confirm"
        >
          {t("invite_card.confirm")}
        </button>
        <button
          className="suggest-create-card__btn suggest-create-card__btn--ghost"
          onClick={onCancel}
          data-testid="invite-cancel"
        >
          {t("invite_card.cancel")}
        </button>
      </div>
    </div>
  );
}
