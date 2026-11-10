/** Only explicitly marked generated titles are translated. Legacy/user titles
 * remain verbatim, even when they happen to be named "New Session". This marker
 * never decides whether a conversation is empty, reusable, or safe to delete. */
export function threadDisplayTitle(
  thread: { id?: string; title: string; defaultTitle?: boolean; temporary?: boolean },
  translate: (key: string) => string,
): string {
  if (thread.temporary) return translate("companion.temporary");
  return thread.defaultTitle === true && thread.title === "New Session"
    ? translate("workspace.newConversation") : thread.title;
}

interface Titled { id: string; title: string; defaultTitle?: boolean; userTitled?: boolean }

/** The user's own name for a conversation (sidebar or header rename). An empty name changes nothing.
 *
 * `userTitled` is what keeps it: a name the user typed can look exactly like a placeholder ("New Session"), so the
 * title alone cannot say "never auto-title this again". It is persisted with the thread (sessionPersistence). */
export function renameThread<T extends Titled>(threads: T[], id: string, title: string): T[] {
  const next = title.trim();
  if (!next) return threads;
  return threads.map((thread) => (thread.id === id
    ? { ...thread, title: next, defaultTitle: undefined, userTitled: true } : thread));
}

/** Whether the first user message may replace a thread's placeholder title. Only App's fallback for a chat with no
 * `onSendMessage` reaches this today, but `userTitled` stays checked: a name the user typed can read "New Session",
 * and it must never be overwritten if that path becomes reachable. */
export function firstMessageMayRetitle(thread: { title: string; temporary?: boolean; userTitled?: boolean }): boolean {
  return !thread.temporary && !thread.userTitled
    && (thread.title === "New Session" || thread.title.startsWith("Orchestration thread"));
}

/** A generated title lands only on a thread the user has not named; the titler can answer after a rename. */
export function applyGeneratedTitle<T extends Titled>(threads: T[], id: string, title: string): T[] {
  return threads.map((thread) => (thread.id === id && !thread.userTitled
    ? { ...thread, title, defaultTitle: undefined } : thread));
}
