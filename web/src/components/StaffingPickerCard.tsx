import { useTranslation } from "react-i18next";
import type { SuggestDraft } from "../api/client.types";

interface Candidate {
  spawnId: number;
  name: string | null;
  score: number;
  why: string;
}

interface Props {
  candidates: Candidate[];
  createDraft: SuggestDraft | null;
  onInvite: (spawnId: number) => void;
  onCreateNew: (draft: SuggestDraft) => void;
  onDismiss: () => void;
}

/**
 * Staffing picker card shown when a `propose_staffing` frame arrives.
 * Lists candidate spawns with invite buttons, and optionally a "build new"
 * action that opens the existing SuggestCreateCard flow with the createDraft.
 */
export default function StaffingPickerCard({
  candidates,
  createDraft,
  onInvite,
  onCreateNew,
  onDismiss,
}: Props) {
  const { t } = useTranslation();

  return (
    <div className="suggest-create-card staffing-picker-card" data-testid="staffing-picker-card">
      <header className="suggest-create-card__head">
        <span className="suggest-create-card__icon" aria-hidden>⊕</span>
        <span className="suggest-create-card__title">
          {t("staffing_card.heading", { count: candidates.length })}
        </span>
      </header>

      <div className="staffing-picker-card__list">
        {candidates.map((c) => {
          const name = c.name ?? `#${c.spawnId}`;
          return (
            <div
              key={c.spawnId}
              className="staffing-picker-card__row"
              data-testid={`staffing-candidate-${c.spawnId}`}
            >
              <div className="staffing-picker-card__info">
                <div className="staffing-picker-card__name-row">
                  <span className="staffing-picker-card__name">{name}</span>
                  <span
                    className="staffing-picker-card__score"
                    data-testid={`staffing-score-${c.spawnId}`}
                  >
                    {Math.round(c.score * 100)}%
                  </span>
                </div>
                <span className="staffing-picker-card__why">
                  <span className="staffing-picker-card__why-label">
                    {t("staffing_card.why")}
                  </span>
                  {c.why}
                </span>
              </div>
              <button
                type="button"
                className="suggest-create-card__btn suggest-create-card__btn--primary staffing-picker-card__invite-btn"
                onClick={() => onInvite(c.spawnId)}
                data-testid={`staffing-invite-${c.spawnId}`}
              >
                {t("staffing_card.invite")}
              </button>
            </div>
          );
        })}
      </div>

      <div className="suggest-create-card__actions">
        {createDraft && (
          <button
            type="button"
            className="suggest-create-card__btn suggest-create-card__btn--ghost"
            onClick={() => onCreateNew(createDraft)}
            data-testid="staffing-build-new"
          >
            {t("staffing_card.buildNew")}
          </button>
        )}
        <button
          type="button"
          className="suggest-create-card__btn suggest-create-card__btn--ghost"
          onClick={onDismiss}
          data-testid="staffing-dismiss"
        >
          {t("staffing_card.dismiss")}
        </button>
      </div>
    </div>
  );
}
