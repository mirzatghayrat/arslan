import { useState } from "react";
import { useTranslation } from "react-i18next";
import { MessageCircle, Trash2 } from "lucide-react";
import { useWorkbench, type SideTab } from "../../stores/workbenchStore";
import { toast } from "../kit";
import { HEADING } from "./FilesTab";

const EMPTY: never[] = [];

/** "Side chat 3": a side chat's name is its place among its conversation's side chats, oldest first. */
export function sideName(t: (k: string, o?: Record<string, unknown>) => string, n: number): string {
  return t("sideChat.tab", { n });
}

/**
 * SIDE-2: Overview's "Side chats" (the user, 2026-11-11, A): every side chat of this conversation, open or closed. A row
 * reopens its tab; each can be deleted on its own after a confirm (SIDE-1 deletes it only when named as one).
 */
export default function SideChatsList({ conversationId }: { conversationId: string }) {
  const { t } = useTranslation();
  const sides = useWorkbench((s) => s.sides[conversationId] ?? EMPTY);
  const open = useWorkbench((s) => s.openSides[conversationId] ?? EMPTY);
  const { openSide, deleteSide } = useWorkbench.getState();
  const [asking, setAsking] = useState<string | null>(null);
  if (sides.length === 0) return null;
  const remove = async (id: SideTab) => {
    try { await deleteSide(conversationId, id); toast(t("sideChat.deleted")); } catch { toast(t("sideChat.deleteFailed")); }
    setAsking(null);
  };
  return (
    <section data-testid="overview-side-chats">
      <h3 className={HEADING}>{t("sideChat.listH")}</h3>
      <ul className="mt-1 space-y-0.5">{sides.map((chat, i) => {
        const id = chat.conversation_id as SideTab;
        return <li key={id} data-testid={`overview-side-${id}`}>
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => openSide(conversationId, id)} data-testid="overview-side-open"
              className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-1 text-left text-[12.5px] hover:bg-foreground/[0.04]">
              <MessageCircle size={13} className="shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{sideName(t, i + 1)}</span>
              {!open.includes(id) && <span className="shrink-0 text-[11px] text-subtle-foreground">{t("sideChat.closed")}</span>}
            </button>
            <button type="button" aria-label={t("sideChat.delete")} title={t("sideChat.delete")} data-testid="overview-side-delete"
              onClick={() => setAsking(id)} className="shrink-0 rounded-md p-1 text-subtle-foreground hover:bg-foreground/5 hover:text-danger">
              <Trash2 size={13} /></button>
          </div>
          {asking === id && <div role="alertdialog" aria-label={t("sideChat.delete")} data-testid="overview-side-confirm"
            className="mt-1 flex flex-col gap-2 rounded-lg border border-border bg-background p-2.5 text-[12px]">
            <p>{t("sideChat.deleteAsk")}</p>
            <div className="flex justify-end gap-1.5">
              <button type="button" onClick={() => setAsking(null)} className="rounded-md border border-border px-2.5 py-1">{t("sideChat.cancel")}</button>
              <button type="button" onClick={() => void remove(id)} data-testid="overview-side-confirm-delete"
                className="rounded-md bg-danger px-2.5 py-1 text-white">{t("sideChat.confirmDelete")}</button>
            </div>
          </div>}
        </li>;
      })}</ul>
    </section>
  );
}
