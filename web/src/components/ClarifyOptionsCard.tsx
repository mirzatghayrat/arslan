import { useTranslation } from "react-i18next";

interface Props {
  /** The clarifying question Arslan needs answered before it can proceed. */
  question: string;
  /** 2-4 options, validated/clamped server-side. Label is the text sent on pick. */
  options: { label: string; hint?: string }[];
  /** True once the user picked — buttons disable (one-shot; a re-click never re-sends). */
  answered?: boolean;
  /** Called with the picked option's LABEL — sent as a normal user_message. */
  onPick: (label: string) => void;
}

/**
 * PA-3 structured clarification card for a backend `clarify_options` frame. Renders
 * inline in the chat flow (same visual family as InviteConfirmCard): the question +
 * 2-4 one-click option buttons (label bold, hint muted). Picking an option sends the
 * label over the SAME WS send path the composer uses, so one click advances the
 * conversation instead of a free-text counter-question restarting the confirm loop.
 */
export default function ClarifyOptionsCard({ question, options, answered, onPick }: Props) {
  const { t } = useTranslation();

  return (
    <div
      className={`clarify-card${answered ? " clarify-card--answered" : ""}`}
      data-testid="clarify-options-card"
    >
      <span className="clarify-card__question">{question}</span>
      <div className="clarify-card__options">
        {options.map((o) => (
          <button
            key={o.label}
            type="button"
            className="clarify-card__option"
            data-testid="clarify-option"
            disabled={!!answered}
            onClick={() => onPick(o.label)}
          >
            <span className="clarify-card__label">{o.label}</span>
            {o.hint && <span className="clarify-card__hint">{o.hint}</span>}
          </button>
        ))}
      </div>
      {answered && (
        <span className="clarify-card__done" data-testid="clarify-answered">
          ✓ {t("clarify_card.answered")}
        </span>
      )}
    </div>
  );
}
