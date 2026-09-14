/** Only explicitly marked generated titles are translated. Legacy/user titles
 * remain verbatim, even when they happen to be named "New Session". This marker
 * never decides whether a conversation is empty, reusable, or safe to delete. */
export function threadDisplayTitle(
  thread: { title: string; defaultTitle?: boolean; temporary?: boolean },
  translate: (key: string) => string,
): string {
  if (thread.temporary) return translate("companion.temporary");
  return thread.defaultTitle === true && thread.title === "New Session"
    ? translate("workspace.newConversation") : thread.title;
}
