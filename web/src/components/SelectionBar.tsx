import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { CornerUpLeft, MessageCircle } from "lucide-react";
import { quoteIntoMain } from "../lib/quote";
import { useWorkbench } from "../stores/workbenchStore";
import { toast } from "./kit";

/** The reply a node sits in: the main conversation's Arslan replies carry `data-reply-id` (their message id). */
function replyOf(node: Node | null): HTMLElement | null {
  const el = node instanceof Element ? node : node?.parentElement ?? null;
  return el?.closest<HTMLElement>("[data-reply-id]") ?? null;
}

type Picked = { text: string; replyId: number | null; left: number; top: number };

/** What is selected, when it lies inside one reply. A reply still streaming, or not stored yet, has no id to branch at. */
export function pickedReply(sel: Selection | null): Omit<Picked, "left" | "top"> & { range: Range } | null {
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
  const reply = replyOf(sel.anchorNode);
  if (!reply || reply !== replyOf(sel.focusNode)) return null;
  const text = sel.toString().trim();
  if (!text) return null;
  const raw = reply.dataset.replyId ?? "";
  const replyId = /^[1-9]\d*$/.test(raw) ? Number(raw) : null;
  return { text, replyId, range: sel.getRangeAt(0) };
}

/**
 * SIDE-2 (v0.1.64, SIDE-0's mock): select text in one of Arslan's replies and a small bar floats above it, with
 * "Start a side chat" (a side chat branched at that reply, the selection waiting as a quote in its input; nothing is
 * sent) and "Reply" (the selection as a quote in the main input).
 */
export default function SelectionBar({ conversationId, canBranch }: { conversationId: string; canBranch: boolean }) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<Picked | null>(null);

  const look = useCallback(() => {
    const found = pickedReply(window.getSelection());
    if (!found) { setPicked(null); return; }
    const r = typeof found.range.getBoundingClientRect === "function" ? found.range.getBoundingClientRect() : null;
    setPicked({ text: found.text, replyId: found.replyId,
      left: r ? Math.max(8, Math.min(window.innerWidth - 248, r.left + r.width / 2 - 120)) : 8,
      top: r ? Math.max(8, r.top - 44) : 8 });
  }, []);
  useEffect(() => {
    document.addEventListener("selectionchange", look);
    document.addEventListener("mouseup", look);
    document.addEventListener("keyup", look);
    return () => {
      document.removeEventListener("selectionchange", look);
      document.removeEventListener("mouseup", look);
      document.removeEventListener("keyup", look);
    };
  }, [look]);
  if (!picked) return null;

  const done = () => { window.getSelection()?.removeAllRanges(); setPicked(null); };
  const start = () => {
    const { text, replyId } = picked;
    done();
    useWorkbench.getState().startSide(conversationId, replyId, text).catch(() => toast(t("sideChat.startFailed")));
  };
  const reply = () => { quoteIntoMain(picked.text); done(); toast(t("sideChat.quoted")); };
  const button = "inline-flex items-center gap-1.5 whitespace-nowrap rounded-[7px] px-2.5 py-1.5 text-[12px] hover:bg-fill";
  return createPortal(
    // mousedown kept from the page, so the click doesn't drop the selection first
    <div role="toolbar" aria-label={t("sideChat.barLabel")} data-testid="selection-bar" onMouseDown={(e) => e.preventDefault()}
      style={{ left: picked.left, top: picked.top }}
      className="fixed z-50 flex gap-0.5 rounded-[10px] border border-border-strong bg-background p-[3px] text-foreground shadow-lg">
      {canBranch && picked.replyId != null && <>
        <button type="button" className={button} onClick={start} data-testid="selection-start-side">
          <MessageCircle size={13} aria-hidden />{t("sideChat.start")}</button>
        <span className="mx-px my-1 w-px bg-border" aria-hidden />
      </>}
      <button type="button" className={button} onClick={reply} data-testid="selection-reply">
        <CornerUpLeft size={13} aria-hidden />{t("sideChat.reply")}</button>
    </div>,
    document.body,
  );
}
