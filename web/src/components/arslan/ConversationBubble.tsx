import { useTranslation } from "react-i18next";
import type { ArslanThreadItem } from "../../types";
import RoutingCaption from "./RoutingCaption";
import MarkdownArtifact, { LONG_OUTPUT_THRESHOLD } from "./MarkdownArtifact";
import EquipmentChips from "./EquipmentChips";

export default function ConversationBubble({
  item,
  children,
  live = false,
}: {
  item: ArslanThreadItem;
  children?: React.ReactNode;
  live?: boolean;
}) {
  const { t } = useTranslation();

  if (item.kind === "system") {
    const name = item.content.startsWith("__SPAWN_CREATED__:")
      ? item.content.slice("__SPAWN_CREATED__:".length)
      : item.content;
    return (
      <div className="flex flex-col items-center gap-2">
        <span className="rounded-full border border-amber/30 bg-amber/10 px-3 py-1 text-xs text-amber/90">
          {t("conversation.spawn_created", { name })}
        </span>
        {item.intro && (
          <div className="max-w-[75%] rounded-2xl border border-amber/20 bg-amber/5 px-4 py-3 text-sm text-white/80">
            <p className="whitespace-pre-wrap">{item.intro}</p>
            {item.equipment && (
              <div className="mt-2">
                <EquipmentChips equipment={item.equipment} />
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  if (item.kind === "fact") {
    return (
      <div className="flex justify-center">
        <span className="rounded-full border border-amber/30 bg-amber/10 px-3 py-1 text-xs text-amber/90">
          <span aria-hidden>🐆 </span>
          {t("conversation.remember_note")} {item.content}
        </span>
      </div>
    );
  }

  const isUser = item.role === "user";
  const isSpawn = item.role === "spawn";
  const tone = isUser
    ? "bg-amber/15 text-amber"
    : isSpawn
      ? "bg-purple-500/15 text-purple-100"
      : "bg-white/5 text-white/90";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className="max-w-[75%]">
        {isSpawn && <RoutingCaption spawnName={item.spawnName} />}
        <div className={`rounded-2xl px-4 py-2.5 ${tone}`}>
          {isSpawn && (
            <p className="mb-1 text-xs font-semibold text-purple-200">
              <span aria-hidden>💬 </span>
              {item.spawnName ?? t("conversation.title")}
            </p>
          )}
          {!live && item.content.length > LONG_OUTPUT_THRESHOLD ? (
            <MarkdownArtifact
              title={isSpawn ? item.spawnName ?? t("conversation.title") : t("conversation.title")}
              content={item.content}
              downloadName={`${(isSpawn ? item.spawnName : "arslan") ?? "arslan"}-${item.id}.md`}
            />
          ) : (
            <p className="whitespace-pre-wrap">{item.content}</p>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}
