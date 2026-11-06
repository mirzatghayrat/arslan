import { useEffect, useRef } from "react";
import { notificationTarget, OPEN_CONVERSATION_EVENT } from "../lib/openConversation";
import type { Section } from "../lib/sections";
import { subscribeOpenConversation } from "../lib/shell";

/** Where a clicked proactive notice leads (`@progress`) until Progress can show what was noticed: the Scheduled page, which lists the
 *  watched pages and folders, the only things whose changes notify (#605 review F1). INB7 moves it to Progress. */
export const PROGRESS_NOTICE_SECTION: Section = "scheduled";

/** A clicked desktop notification (0.1.41), and an in-app link to an earlier conversation (0.1.52 S3), lead to the same places: a
 *  conversation the user has and has not archived, or, for a proactive notice, the page that shows it. A ref keeps the one subscription
 *  pointed at the current threads and handlers. App's own wiring, a hook of its own so it is tested as App uses it. */
export function useNotificationRoutes({ threads, selectConversation, openSection }: {
  threads: { id: string; archived?: boolean }[];
  selectConversation: (id: string) => void;
  openSection: (section: Section) => void;
}) {
  const route = useRef<(id: string) => void>(() => {});
  route.current = (id: string) => {
    const target = notificationTarget(id, threads);
    if (target?.kind === "progress") openSection(PROGRESS_NOTICE_SECTION);
    else if (target) selectConversation(target.id);
  };
  useEffect(() => subscribeOpenConversation((id) => route.current(id)), []);
  useEffect(() => {
    const onLink = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (typeof id === "string" && id) route.current(id);
    };
    window.addEventListener(OPEN_CONVERSATION_EVENT, onLink);
    return () => window.removeEventListener(OPEN_CONVERSATION_EVENT, onLink);
  }, []);
}
