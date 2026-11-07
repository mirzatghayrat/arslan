/** Which thread a clicked desktop notification may open, if any (0.1.41).
 *  Only an existing, non-archived conversation: the id arrives from outside the
 *  page, so it selects from what the user already has, never creates one. */
export function conversationToOpen(id: string, threads: { id: string; archived?: boolean }[]): string | null {
  const thread = threads.find(t => t.id === id);
  return thread && !thread.archived ? thread.id : null;
}

/** 0.1.52 S3: an in-app link to an earlier conversation, as conversation_search returns it. */
export const CONVERSATION_LINK_PREFIX = "#conversation=";
export const OPEN_CONVERSATION_EVENT = "arslan-open-conversation";

export function conversationFromLink(href: string | undefined): string | null {
  if (!href || !href.startsWith(CONVERSATION_LINK_PREFIX)) return null;
  try {
    const id = decodeURIComponent(href.slice(CONVERSATION_LINK_PREFIX.length)).trim();
    return id && id.length <= 100 ? id : null;
  } catch {
    return null;
  }
}
