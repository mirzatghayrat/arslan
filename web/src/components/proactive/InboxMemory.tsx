import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { loadPendingMemory, type PendingMemoryItem } from "../../lib/pendingMemory";
import { announceProactiveChange } from "../../api/proactive";
import { openSection } from "../../lib/sections";
import { Button, ProposalRow, Tag } from "../kit";

/**
 * "记忆等你确认" in the Inbox (0.1.55 §12): the first few of the merged pending memory
 * list (§13), answerable here; "Open Memory" for the rest. Hidden when nothing waits.
 */
export default function InboxMemory({ max = 3, onCount }: { max?: number; onCount?: (n: number) => void }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<PendingMemoryItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(async () => {
    let next: PendingMemoryItem[] = [];
    try { next = await loadPendingMemory(t); } catch { /* nothing shown */ }
    setItems(next);
    onCount?.(next.length);
  }, [t, onCount]);
  useEffect(() => { void load(); }, [load]);

  async function act(item: PendingMemoryItem, run: () => Promise<unknown>) {
    setBusy(item.key);
    try { await run(); } catch { /* the row stays; Memory has the same controls */ }
    finally { setBusy(null); announceProactiveChange(); await load(); }
  }
  if (!items.length) return null;
  return (
    <section data-testid="inbox-memory" aria-label={t("inbox.memoryWaiting")} className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-[13px] font-semibold">
        <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full bg-subtle-foreground" />{t("inbox.memoryWaiting")}
        <span className="font-mono text-[12px] text-subtle-foreground">{items.length}</span>
        <button type="button" onClick={() => openSection("brain")}
          className="ml-auto text-[12px] font-normal text-muted-foreground hover:text-foreground">{t("inbox.memoryOpen")} ›</button>
      </h2>
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {items.slice(0, max).map((item, i) => (
          <div key={item.key} className={i ? "border-t border-border" : ""}>
            <ProposalRow testId={`pending-memory-${item.key}`} text={item.text}
              meta={<><Tag>{t(`pendingMemory.source.${item.source}`)}</Tag>{item.sensitive ? <Tag tone="danger">{t("pendingMemory.sensitive")}</Tag> : null}</>}
              actions={<>
                <Button size="sm" tone="primary" disabled={busy === item.key} onClick={() => void act(item, item.accept)}>
                  {item.source === "curation" ? t("pendingMemory.apply") : item.source === "lesson" ? t("pendingMemory.use")
                    : item.sensitive ? t("pendingMemory.keepLocal") : t("pendingMemory.keep")}
                </Button>
                <Button size="sm" disabled={busy === item.key} onClick={() => void act(item, item.reject)}>{t("pendingMemory.drop")}</Button>
              </>} />
          </div>
        ))}
      </div>
    </section>
  );
}
