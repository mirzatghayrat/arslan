import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { ApiError, api, type BrainEntry, type BrainLeaf } from "../../api/client";

/** Slide-in detail for a clicked brain node: real excerpt + provenance + usage.
 *
 * F0.5 wires up three payload fields the backend has emitted since the P1/D rounds and
 * that NO brain component read until now: `sensitive`, `provenance_record` and
 * `superseded_by` (the last one gating the undo affordance).
 */
export default function BrainEntryDetail(
  { leaf, onClose, onChanged }: { leaf: BrainLeaf; onClose: () => void; onChanged?: () => void },
) {
  const [entry, setEntry] = useState<BrainEntry | null>(null);
  const [undoing, setUndoing] = useState(false);
  const [undoErr, setUndoErr] = useState<string | null>(null);

  const load = () => {
    let ok = true;
    setEntry(null);
    api.getBrainEntry(leaf.kind, leaf.ref)
      .then((e) => { if (ok) setEntry(e); })
      .catch(() => { if (ok) setEntry(null); });
    return () => { ok = false; };
  };
  useEffect(load, [leaf]);   // eslint-disable-line react-hooks/exhaustive-deps

  // 🔴 The gate is `superseded_by != null`, NOT the kind. Gating on kind alone would put
  // the button on every active profile/learning entry, where the server answers 409
  // "already active" — an affordance that exists only to fail. Kind still matters as a
  // second condition: only user_facts and learnings have a superseded_by column at all,
  // so material can never be un-superseded (the server 422s it), and `note` never even
  // reaches this component (BrainSection routes notes to NoteEditor).
  const canUndo =
    entry != null &&
    entry.superseded_by != null &&
    (leaf.kind === "profile" || leaf.kind === "learning");

  const undo = async () => {
    setUndoing(true);
    setUndoErr(null);
    try {
      await api.undoSupersede(leaf.kind as "profile" | "learning", leaf.ref);
      // 🔴 Refetch. Writing and leaving the panel frozen is the exact "I clicked and
      // nothing moved" failure the evolution panel just shipped; do not repeat it here.
      load();
      onChanged?.();
    } catch (e) {
      setUndoErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setUndoing(false);
    }
  };

  return (
    <div className="absolute top-0 right-0 h-full w-[360px] bg-surface-raised border-l border-border p-4 overflow-auto z-20"
      data-testid="brain-entry-detail">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[13px] font-medium text-foreground truncate">
          {entry?.sensitive && (
            <span title="已标记为敏感" data-testid="entry-sensitive" className="mr-1">🔒</span>
          )}
          {leaf.label}
        </span>
        <button onClick={onClose} aria-label="关闭详情" className="text-subtle-foreground hover:text-foreground">
          <X className="w-4 h-4" />
        </button>
      </div>
      {entry == null ? (
        <div className="text-[11px] text-subtle-foreground">loading…</div>
      ) : (
        <>
          <div className="text-[10.5px] text-subtle-foreground font-mono mb-2">
            {entry.provenance ?? ""}
            {` · 用过 ${entry.usage_count}`}
            {entry.last_used_ref ? ` · 最近用于 ${entry.last_used_ref}` : ""}
          </div>

          {entry.superseded_by != null && (
            <div className="mb-2 text-[11px] text-warning" data-testid="entry-superseded">
              已被 #{entry.superseded_by} 取代 — 不再注入给分身
              {canUndo && (
                <button className="ml-2 underline disabled:opacity-50" disabled={undoing}
                  onClick={() => void undo()} data-testid="undo-supersede">
                  {undoing ? "撤销中…" : "撤销取代"}
                </button>
              )}
            </div>
          )}
          {undoErr && <div className="mb-2 text-[11px] text-danger" role="alert">{undoErr}</div>}

          {entry.sensitive && (
            <div className="mb-2 text-[10.5px] text-subtle-foreground" data-testid="sensitive-note">
              已标记为敏感。这是一个显示提示,不是隔离 —— 内容照常返回给读取它的界面。
            </div>
          )}

          <div className="text-[12px] text-foreground whitespace-pre-wrap leading-relaxed">{entry.excerpt}</div>

          {entry.provenance_record && Object.keys(entry.provenance_record).length > 0 && (
            <details className="mt-3 text-[10.5px] text-subtle-foreground" data-testid="provenance-record">
              <summary className="cursor-pointer">出处记录</summary>
              <pre className="mt-1 whitespace-pre-wrap break-all font-mono">
                {JSON.stringify(entry.provenance_record, null, 2)}
              </pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}
