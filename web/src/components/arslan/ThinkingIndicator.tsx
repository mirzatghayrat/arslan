import { useTranslation } from "react-i18next";
import NodeBar from "./NodeBar";

export default function ThinkingIndicator({ spawnName }: { spawnName?: string | null }) {
  const { t } = useTranslation();
  const label = spawnName ? t("conversation.thinking_spawn", { name: spawnName }) : t("conversation.thinking_arslan");
  const state = spawnName ? "spawn_working" : "thinking";
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-2 rounded-2xl bg-white/5 px-4 py-2.5 text-sm text-brand-text/70">
        <NodeBar state={state} />
        <span>{label}</span>
      </div>
    </div>
  );
}
