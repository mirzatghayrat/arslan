import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUp, CornerUpLeft, Info, Lock, X } from "lucide-react";
import type { SideChat } from "../../api/sideChats";
import { useSideChat } from "../../hooks/useSideChat";
import { quoteIntoMain, withQuote } from "../../lib/quote";
import { useWorkbench, type SideTab } from "../../stores/workbenchStore";
import { ComposerInput } from "../ComposerInput";
import CopyButton from "../CopyButton";
import MessageBody from "../MessageBody";
import { toast } from "../kit";

const act = "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-muted-foreground hover:bg-foreground/5 hover:text-foreground";

/** The quote above an input (SIDE-0's mock): a primary rule on the left, three lines at most, a remove button. */
export function QuoteChip({ text, onRemove }: { text: string; onRemove?: () => void }) {
  const { t } = useTranslation();
  return (
    <div data-testid="side-quote" className="flex items-start gap-2 rounded-r-lg border-l-2 border-primary bg-fill px-2.5 py-1.5 text-[11.5px] leading-normal text-muted-foreground">
      <span className="line-clamp-3 min-w-0 flex-1 whitespace-pre-line">{text}</span>
      {onRemove && <button type="button" aria-label={t("sideChat.removeQuote")} title={t("sideChat.removeQuote")} onClick={onRemove}
        className="shrink-0 text-subtle-foreground hover:text-foreground"><X size={13} /></button>}
    </div>
  );
}

/**
 * SIDE-2 (v0.1.64): one side chat in the workbench. It reads its conversation up to the branch, read-only (SIDE-1);
 * the quote picked in the main conversation waits in its input until the user sends. "Bring back to main" on a reply
 * is the only way anything reaches the main conversation, and only into its input (card, rule 1).
 */
export default function SideChatTab({ chat }: { chat: SideChat }) {
  const { t } = useTranslation();
  const id = chat.conversation_id as SideTab;
  const quote = useWorkbench((s) => s.sideQuotes[id] ?? null);
  const setSideQuote = useWorkbench((s) => s.setSideQuote);
  const { lines, streaming, busy, send } = useSideChat(id);
  const [value, setValue] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { input.current?.focus(); }, [id]);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [lines.length, streaming]);

  const submit = () => {
    const content = withQuote(quote, value);
    if (!content || busy) return;
    send(content);
    setValue("");
    setSideQuote(id, null);
  };
  const bringBack = (text: string) => {
    quoteIntoMain(text, { sideId: id, marked: chat.outside_at_start });
    toast(t("sideChat.broughtBack"));
  };

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="side-chat-tab">
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
        <p className="flex items-start gap-1.5 text-[11px] leading-normal text-subtle-foreground">
          <Lock size={12} className="mt-0.5 shrink-0" aria-hidden />{t("sideChat.scope")}</p>
        {/* The user, 2026-11-11 (B): one quiet line when the side chat started marked. */}
        {chat.outside_at_start && <p data-testid="side-outside" className="flex items-start gap-1.5 rounded-lg bg-fill px-2.5 py-1.5 text-[11px] leading-normal text-muted-foreground">
          <Info size={12} className="mt-0.5 shrink-0 text-info" aria-hidden />{t("sideChat.outside")}</p>}
        {lines.length === 0 && streaming == null
          && <p className="m-auto max-w-[260px] text-center text-[12px] leading-relaxed text-subtle-foreground">{t("sideChat.empty")}</p>}
        {lines.map((line) => line.role === "user"
          ? <div key={line.id} className="ml-auto max-w-[88%] whitespace-pre-line rounded-[12px_12px_4px_12px] border border-border bg-fill px-3 py-2 text-[12.5px]"
            data-testid="side-user-line">{line.text}</div>
          : <div key={line.id} className="group/side min-w-0" data-testid="side-reply">
            <MessageBody text={line.text} className="text-[12.5px] leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />
            <div className="mt-1 flex items-center gap-1">
              <CopyButton text={line.text} className={act} />
              <button type="button" className={`${act} text-foreground`} data-testid="side-bring-back" onClick={() => bringBack(line.text)}>
                <CornerUpLeft size={12} aria-hidden />{t("sideChat.bringBack")}</button>
            </div>
          </div>)}
        {streaming != null && <div data-testid="side-streaming">
          {streaming ? <MessageBody text={streaming} streaming className="text-[12.5px] leading-relaxed" />
            : <span className="text-[12px] text-subtle-foreground">{t("sideChat.thinking")}</span>}</div>}
        <div ref={end} />
      </div>
      <div className="px-3 pb-3 pt-1">
        <div className="composer-box flex flex-col gap-1.5">
          {quote && <QuoteChip text={quote} onRemove={() => setSideQuote(id, null)} />}
          <ComposerInput ref={input} value={value} aria-label={t("sideChat.placeholder")} placeholder={t("sideChat.placeholder")}
            data-testid="side-input" onChange={(e) => setValue(e.target.value)} onSend={(e) => { e.preventDefault(); submit(); }}
            className="block w-full resize-none bg-transparent px-1 py-1 text-xs leading-relaxed text-foreground placeholder-subtle-foreground focus:outline-none" />
          <div className="flex justify-end">
            <button type="button" aria-label={t("sideChat.send")} title={t("sideChat.send")} data-testid="side-send" onClick={submit}
              disabled={busy || (!value.trim() && !quote)}
              className="grid h-7 w-7 place-items-center rounded-lg bg-primary text-primary-foreground hover:bg-primary-hover disabled:opacity-40">
              <ArrowUp size={14} /></button>
          </div>
        </div>
      </div>
    </div>
  );
}
