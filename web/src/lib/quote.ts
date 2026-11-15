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

export function quoteIntoMain(text: string): void {
  if (!text.trim()) return;
  window.dispatchEvent(new CustomEvent(MAIN_QUOTE_EVENT, { detail: text }));
}

/** What the composer holds after a quote is added to `current`: the quote on its own lines, the cursor after it. */
export function addQuote(current: string, text: string): string {
  const block = `${asQuote(text)}\n\n`;
  return current.trim() ? `${current.replace(/\s+$/, "")}\n\n${block}` : block;
}
