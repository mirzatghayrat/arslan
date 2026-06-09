import { useTranslation } from "react-i18next";

export default function RoutingCaption({ spawnName }: { spawnName: string | null | undefined }) {
  const { t } = useTranslation();
  return (
    <p className="mb-1 text-xs text-white/40">
      <span aria-hidden>🐆 </span>
      {t("conversation.routed_to", { name: spawnName ?? t("conversation.title") })}
    </p>
  );
}
