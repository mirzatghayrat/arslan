import { useTranslation } from "react-i18next";

interface Props {
  onFeedback: (action: "thumbs_up" | "thumbs_down") => void;
  onEdit: () => void;
}

export default function FeedbackBar({ onFeedback, onEdit }: Props) {
  const { t } = useTranslation();
  return (
    <div className="mt-1 flex gap-2 text-xs text-white/40">
      <button aria-label={t("chat.thumbs_up")} onClick={() => onFeedback("thumbs_up")}>
        👍
      </button>
      <button aria-label={t("chat.thumbs_down")} onClick={() => onFeedback("thumbs_down")}>
        👎
      </button>
      <button aria-label={t("chat.edit")} onClick={onEdit}>
        ✏️
      </button>
    </div>
  );
}
