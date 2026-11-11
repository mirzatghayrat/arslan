import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CornerUpLeft } from "lucide-react";
import { subSessionSpend } from "../api/client";
import type { ConversationMeta } from "../lib/conversationMeta";
import { ancestors, buildForest, descendants, subStatus } from "../lib/subTree";
import { threadDisplayTitle } from "../lib/threadTitles";
import SubStatusIcon from "./SubStatusIcon";
import { Button } from "./kit";

/** Each tree's sub-sessions may spend this many times the per-task dollar limit together (sub_sessions.TREE_CAP_MULTIPLIER). */
export const TREE_CAP_MULTIPLIER = 3;

interface Thread { id: string; title: string; defaultTitle?: boolean }

/** SUB5d (the approved mock), above a conversation's messages. In a sub-session: whose it is, with the way back. In a
 *  conversation that started sub-sessions: each one's status, name and an Open button, as a progress view that stays,
 *  and what the tree has spent against its limit (the per-task dollar limit × 3, as Settings → Advanced has it). */
export default function SubSessionBar({ conversationId, threads, meta, usdCap, usdCapEnabled, onOpen }: {
  conversationId: string;
  threads: Thread[];
  meta: Record<string, ConversationMeta | undefined>;
  usdCap: number;
  usdCapEnabled: boolean;
  onOpen: (id: string) => void;
}) {
  const { t } = useTranslation();
  const forest = buildForest(threads.map(thread => thread.id), meta);
  const byId = new Map(threads.map(thread => [thread.id, thread]));
  const name = (id: string) => { const thread = byId.get(id); return thread ? threadDisplayTitle(thread, t) : id; };
  const parent = forest.parentOf[conversationId];
  const below = descendants(conversationId, forest);
  // Fetched again whenever a status under it changes, so the line follows the work.
  const statuses = below.map(id => `${id}:${meta[id]?.state ?? ""}`).join(",");
  const [spent, setSpent] = useState<number | null>(null);
  useEffect(() => {
    if (!statuses) { setSpent(null); return; }
    let cancelled = false;
    subSessionSpend(conversationId).then(got => { if (!cancelled) setSpent(got.spent_usd); }, () => {});
    return () => { cancelled = true; };
  }, [conversationId, statuses]);
  if (!parent && !below.length) return null;
  const usd = (value: number) => `$${value.toFixed(2)}`;
  const depthOf = (id: string) => ancestors(id, forest).indexOf(conversationId);
  return <div className="mx-auto mb-4 flex w-full max-w-3xl flex-col gap-2" data-testid="sub-session-bar">
    {parent && <div className="flex items-center gap-2 rounded-lg bg-fill px-3 py-2 text-[12.5px] text-muted-foreground" data-testid="sub-session-header">
      <span className="min-w-0 flex-1">{t("subTree.header", { name: name(parent) })}</span>
      <button type="button" onClick={() => onOpen(parent)} data-testid="sub-session-back"
        className="flex shrink-0 items-center gap-1 text-foreground underline-offset-2 hover:underline">
        <CornerUpLeft size={12} aria-hidden />{t("subTree.back", { name: name(parent) })}</button>
    </div>}
    {below.length > 0 && <section aria-label={t("subTree.panel")} data-testid="sub-session-panel"
      className="rounded-xl border border-border bg-background px-3 py-2">
      <div className="mb-1 text-[12px] font-medium text-muted-foreground">{t("subTree.panel")}</div>
      <ul className="flex flex-col">
        {below.map(id => <li key={id} className="flex items-center gap-2 py-1 text-[13px]" style={{ paddingLeft: depthOf(id) * 14 }}
          data-testid={`sub-session-item-${id}`}>
          <SubStatusIcon status={subStatus(meta[id])} />
          <span className="min-w-0 flex-1 truncate">{name(id)}</span>
          <Button size="sm" tone="secondary" onClick={() => onOpen(id)}>{t("subTree.open")}</Button>
        </li>)}
      </ul>
      {spent !== null && <div className="mt-1 border-t border-border pt-1.5 text-[12px] tabular-nums text-subtle-foreground" data-testid="sub-session-spend">
        {usdCapEnabled
          ? t("subTree.spend", { spent: usd(spent), limit: usd(usdCap * TREE_CAP_MULTIPLIER), each: usd(usdCap), times: TREE_CAP_MULTIPLIER })
          : t("subTree.spendNoLimit", { spent: usd(spent) })}
      </div>}
    </section>}
  </div>;
}
