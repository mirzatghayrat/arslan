/** SIDE-2: text as a Markdown quote, one "> " per line. */
export function asQuote(text: string): string {
  return text.trim().split("\n").map((line) => (line ? `> ${line}` : ">")).join("\n");
}

/** A quote and what the user wrote under it, as one message. */
export function withQuote(quote: string | null | undefined, text: string): string {
  const body = text.trim();
  if (!quote?.trim()) return body;
  return body ? `${asQuote(quote)}\n\n${body}` : asQuote(quote);
}

/** The main conversation's composer takes a quote from here ("Reply", "Bring back to main"); it never sends. */
export const MAIN_QUOTE_EVENT = "arslan:composer-quote";

/** Where a quote came from when a side chat's "Bring back to main" put it there (none: the main conversation's "Reply"). */
export type QuoteSource = { sideId: string; marked: boolean };
export type MainQuote = { text: string; from?: QuoteSource };

export function quoteIntoMain(text: string, from?: QuoteSource): void {
  if (!text.trim()) return;
  window.dispatchEvent(new CustomEvent<MainQuote>(MAIN_QUOTE_EVENT, { detail: { text, ...(from ? { from } : {}) } }));
}

/**
 * SIDE-2 follow-up (PR 952's `from_side_chat`): the side chats whose replies were brought back into a composer, by its
 * draft key, until it sends. The main turn that sends one starts marked when that side chat carries outside content
 * (server: `side_chats.carries_outside`).
 */
type Brought = { sideId: string; marked: boolean; lines: string[]; at: number };
const brought = new Map<string, Brought[]>();
let seq = 0;

export function noteBroughtBack(key: string, text: string, from: QuoteSource): void {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  brought.set(key, [...(brought.get(key) ?? []).filter((b) => b.sideId !== from.sideId), { ...from, lines, at: ++seq }]);
}

/** Forget a composer's brought-back quotes (it was sent, or emptied). */
export function forgetBroughtBack(key: string): void {
  brought.delete(key);
  lastNamed.delete(key);
}

/**
 * The side chat a send names, and the composer forgets them all. A quote counts as still there while any of its lines
 * is in `content`: an edited quote keeps it (it errs on the marked side), one deleted outright drops it.
 * The frame names one id, not a list. Two brought back: a side chat the window knows started marked wins, since naming
 * it starts the turn marked for certain; otherwise the most recent. Residual (stated in the PR): when none started
 * marked, a quote from another one whose own runs later read outside content is not the one named.
 */
export function takeBroughtBack(key: string, content: string): string | null {
  const kept = (brought.get(key) ?? []).filter((b) => b.lines.some((line) => content.includes(line)));
  brought.delete(key);
  // A resend of the same text (SMART-3's retry on another model) names what the first send named.
  if (kept.length === 0) return lastNamed.get(key)?.content === content ? lastNamed.get(key)!.sideId : null;
  const pick = kept.find((b) => b.marked) ?? kept.reduce((a, b) => (b.at > a.at ? b : a));
  lastNamed.set(key, { content, sideId: pick.sideId });
  return pick.sideId;
}
const lastNamed = new Map<string, { content: string; sideId: string }>();

/** How a main-conversation send is made (App's `user_message` frame). */
export type SendOpts = { fromClarify?: boolean; fromSideChat?: string };

/** The frame's field for a send that holds a brought-back quote; none for any other send. */
export function sideChatField(opts?: SendOpts): { from_side_chat?: string } {
  return opts?.fromSideChat ? { from_side_chat: opts.fromSideChat } : {};
}

/** What the composer holds after a quote is added to `current`: the quote on its own lines, the cursor after it. */
export function addQuote(current: string, text: string): string {
  const block = `${asQuote(text)}\n\n`;
  return current.trim() ? `${current.replace(/\s+$/, "")}\n\n${block}` : block;
}
