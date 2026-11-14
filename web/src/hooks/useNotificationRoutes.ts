import { useEffect, useRef } from "react";
import { conversationToOpen, OPEN_CONVERSATION_EVENT } from "../lib/openConversation";
import { subscribeOpenConversation, subscribeOpenScheduledTask } from "../lib/shell";

/** A clicked desktop notification (0.1.41), and an in-app link to an earlier conversation (0.1.52 S3), lead to the same places: a
 *  conversation the user has and has not archived. A ref keeps the one subscription
 *  pointed at the current threads and handlers. App's own wiring, a hook of its own so it is tested as App uses it.
 *  SUB5a: a scheduled task paused because its conversation was deleted opens the task on the Scheduled page instead. */
export function useNotificationRoutes({ threads, selectConversation, openScheduledTask }: {
  threads: { id: string; archived?: boolean }[];
  selectConversation: (id: string) => void;
  openScheduledTask?: (taskId: number) => void;
}) {
  const route = useRef<(id: string) => void>(() => {});
  route.current = (id: string) => {
    const target = conversationToOpen(id, threads);
    if (target) selectConversation(target);
  };
  const toTask = useRef(openScheduledTask);
  toTask.current = openScheduledTask;
  useEffect(() => subscribeOpenConversation((id) => route.current(id)), []);
  useEffect(() => subscribeOpenScheduledTask((taskId) => toTask.current?.(taskId)), []);
  useEffect(() => {
    const onLink = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (typeof id === "string" && id) route.current(id);
    };
    window.addEventListener(OPEN_CONVERSATION_EVENT, onLink);
    return () => window.removeEventListener(OPEN_CONVERSATION_EVENT, onLink);
  }, []);
}
