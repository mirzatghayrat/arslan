/** The sidebar's search (v0.1.64, the approved mock): a field at the top of the conversation list, reached with ⌘K,
 *  that filters titles as you type (sub-sessions too, each saying whose it is) and lists the words around each match
 *  in messages (GET /conversations/search: never a temporary, no-memory or sub-session conversation). */
import React, { forwardRef, useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, type ConversationHit } from "../api/client";

/** ⌘K. Not ⌘F: that stays the page's own find. */
export function isSearchKey(event: KeyboardEvent): boolean {
  return (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && (event.code === "KeyK" || event.key.toLowerCase() === "k");
}

/** Messages are searched from this many characters on, as the mock does (the server uses its index from three). */
export const MESSAGE_QUERY_MIN = 2;
const WAIT_MS = 150;

/** `text` as text, with each match of `query` in a <mark> (never parsed as HTML). */
export function Marked({ text, query }: { text: string; query: string }) {
  // Case-insensitive where lowering keeps the length; exact otherwise, so the marks stay on the right characters.
  const fold = text.toLowerCase().length === text.length && query.toLowerCase().length === query.length;
  const hay = fold ? text.toLowerCase() : text;
  const needle = fold ? query.toLowerCase() : query;
  const parts: React.ReactNode[] = [];
  let from = 0;
  if (needle) for (let at = hay.indexOf(needle); at >= 0; at = hay.indexOf(needle, from)) {
    if (at > from) parts.push(text.slice(from, at));
    parts.push(<mark key={at} className="rounded-sm bg-primary/20 px-px text-inherit">{text.slice(at, at + needle.length)}</mark>);
    from = at + needle.length;
  }
  parts.push(text.slice(from));
  return <>{parts}</>;
}

export const SearchField = forwardRef<HTMLInputElement, { value: string; onChange: (value: string) => void }>(
  function SearchField({ value, onChange }, ref) {
    const { t } = useTranslation();
    return <label className="mx-1 mb-1.5 flex h-[30px] shrink-0 items-center gap-1.5 rounded-lg border border-border bg-surface px-2 text-subtle-foreground focus-within:border-primary focus-within:ring-2 focus-within:ring-ring">
      <Search size={14} aria-hidden className="shrink-0" />
      <input ref={ref} type="search" value={value} data-testid="sidebar-search" placeholder={t("sidebar.search.placeholder")}
        aria-label={t("sidebar.search.placeholder")} autoComplete="off" spellCheck={false}
        onChange={event => onChange(event.target.value)}
        onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); onChange(""); } }}
        className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none placeholder:text-subtle-foreground [&::-webkit-search-cancel-button]:hidden" />
      {value
        ? <button type="button" data-testid="sidebar-search-clear" aria-label={t("sidebar.search.clear")}
            onClick={() => { onChange(""); (ref as React.RefObject<HTMLInputElement | null>)?.current?.focus(); }}
            className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded text-subtle-foreground hover:text-foreground"><X size={12} /></button>
        : <kbd className="shrink-0 rounded border border-border px-1 font-mono text-[10.5px] text-subtle-foreground">⌘K</kbd>}
    </label>;
  });

interface ResultsProps {
  /** What was typed, trimmed. */
  query: string;
  /** The sidebar's own conversations, with the title each shows. */
  threads: { id: string; title: string }[];
  /** Each nested sub-session's parent (lib/subTree's forest). */
  parentOf: Record<string, string>;
  onOpen: (id: string) => void;
}

export function SearchResults({ query, threads, parentOf, onOpen }: ResultsProps) {
  const { t } = useTranslation();
  const [found, setFound] = useState<{ query: string; hits: ConversationHit[] }>({ query: "", hits: [] });
  const searchesMessages = query.length >= MESSAGE_QUERY_MIN;
  useEffect(() => {
    if (!searchesMessages) return;
    let live = true;
    const timer = setTimeout(() => {
      api.searchConversations(query).then(hits => hits, () => [] as ConversationHit[])
        .then(hits => { if (live) setFound({ query, hits }); });
    }, WAIT_MS);
    return () => { live = false; clearTimeout(timer); };
  }, [query, searchesMessages]);
  const byId = new Map(threads.map(thread => [thread.id, thread]));
  const needle = query.toLowerCase();
  const titles = threads.filter(thread => thread.title.toLowerCase().includes(needle));
  const hits = searchesMessages && found.query === query ? found.hits.filter(hit => byId.has(hit.conversation_id)) : [];
  const settled = !searchesMessages || found.query === query;
  const heading = (key: string) => <div className="mb-1 mt-2 px-3 text-xs text-muted-foreground first:mt-0">{t(`sidebar.search.${key}`)}</div>;
  const rowClass = "flex w-full min-w-0 flex-col gap-px rounded-lg px-3 py-1.5 text-left text-xs text-foreground hover:bg-foreground/[0.04]";
  if (!titles.length && !hits.length) {
    if (!settled) return null;
    return <div data-testid="sidebar-search-none" className="mx-3 my-5 flex flex-col gap-1 text-center text-[12.5px] text-muted-foreground">
      <b className="font-semibold text-foreground">{t("sidebar.search.none", { query })}</b>
      <span>{t("sidebar.search.noneHint")}</span>
    </div>;
  }
  return <div data-testid="sidebar-search-results" className="space-y-0.5">
    {titles.length > 0 && <>{heading("titles")}
      {titles.map(thread => {
        const parent = byId.get(parentOf[thread.id] ?? "");
        return <button key={thread.id} type="button" data-testid={`search-title-${thread.id}`} onClick={() => onOpen(thread.id)} className={rowClass}>
          <span className="truncate"><Marked text={thread.title} query={query} /></span>
          {parent && <span className="truncate text-[11.5px] text-muted-foreground">{t("subTree.under", { title: parent.title })}</span>}
        </button>;
      })}</>}
    {hits.length > 0 && <>{heading("messages")}
      {hits.map(hit => <button key={hit.message_id} type="button" data-testid={`search-hit-${hit.message_id}`}
        onClick={() => onOpen(hit.conversation_id)} className={rowClass}>
        <span className="truncate">{byId.get(hit.conversation_id)!.title}</span>
        <span data-testid="search-snippet" className="line-clamp-2 break-words text-[11.5px] text-muted-foreground"><Marked text={hit.snippet} query={query} /></span>
      </button>)}</>}
  </div>;
}
