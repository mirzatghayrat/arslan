import { useTranslation } from "react-i18next";
import type { ArslanThreadItem } from "../../types";
import RoutingCaption from "./RoutingCaption";

export default function ConversationBubble({
  item,
  children,
}: {
  item: ArslanThreadItem;
  children?: React.ReactNode;
}) {
  const { t } = useTranslation();

  if (item.kind === "system") {
    const name = item.content.startsWith("__SPAWN_CREATED__:")
      ? item.content.slice("__SPAWN_CREATED__:".length)
      : item.content;
    return (
      <div className="flex justify-center">
        <span className="rounded-full border border-amber/30 bg-amber/10 px-3 py-1 text-xs text-amber/90">
          {t("conversation.spawn_created", { name })}
        </span>
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
          <p className="whitespace-pre-wrap">{item.content}</p>
          {children}
        </div>
      </div>
    </div>
  );
}
