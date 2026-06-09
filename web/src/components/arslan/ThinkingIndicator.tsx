import { useTranslation } from "react-i18next";

export default function ThinkingIndicator({ spawnName }: { spawnName?: string | null }) {
  const { t } = useTranslation();
  const label = spawnName ? t("conversation.thinking_spawn", { name: spawnName }) : t("conversation.thinking_arslan");
  return (
    <div className="flex justify-start">
      <div className="rounded-2xl bg-white/5 px-4 py-2.5 text-sm text-white/60">
        <span className="inline-flex gap-1">
          <span className="animate-pulse">•</span>
          <span className="animate-pulse [animation-delay:150ms]">•</span>
          <span className="animate-pulse [animation-delay:300ms]">•</span>
        </span>
        <span className="ml-2">{label}</span>
      </div>
    </div>
  );
}
