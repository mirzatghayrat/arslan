import { useTranslation } from "react-i18next";

export default function SpawnFeedbackBar({
  onThumbUp,
  onThumbDown,
  onRedo,
  onTweak,
}: {
  onThumbUp: () => void;
  onThumbDown: () => void;
  onRedo: () => void;
  onTweak: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="mt-1 flex gap-2 text-xs text-white/40">
      <button aria-label={t("chat.thumbs_up")} onClick={onThumbUp}>👍</button>
      <button aria-label={t("chat.thumbs_down")} onClick={onThumbDown}>👎</button>
      <button aria-label={t("feedback.redo")} onClick={onRedo}>🔄</button>
      <button aria-label={t("feedback.tweak")} onClick={onTweak}>✏️</button>
    </div>
  );
}
