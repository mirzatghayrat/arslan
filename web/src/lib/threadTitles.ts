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
  if (kind === "remote" || thread.id === "pocket") return translate("sidebar.remote");
  return thread.defaultTitle === true && thread.title === "New Session"
    ? translate("workspace.newConversation") : thread.title;
}
