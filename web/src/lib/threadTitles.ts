/** Only explicitly marked generated titles are translated. Legacy/user titles
 * remain verbatim, even when they happen to be named "New Session". This marker
 * never decides whether a conversation is empty, reusable, or safe to delete. */
export function threadDisplayTitle(
  thread: { id?: string; title: string; defaultTitle?: boolean; temporary?: boolean },
  translate: (key: string) => string,
  kind?: string,
): string {
  if (thread.temporary) return translate("companion.temporary");
  // The phone's own conversation is Remote, not its first message.
  // DELETE-BY: v0.1.64 if the iPhone's Quick Ask (Q1c) ships with it, else v0.1.65 (Q1 card, #4; the user, 2026-10-29): the pocket ("Remote") stays only for phones that don't say `quick`.
  if (kind === "remote" || thread.id === "pocket") return translate("sidebar.remote");
  return thread.defaultTitle === true && thread.title === "New Session"
    ? translate("workspace.newConversation") : thread.title;
}
