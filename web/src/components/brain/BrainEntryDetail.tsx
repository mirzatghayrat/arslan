import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api, type BrainEntry, type BrainLeaf } from "../../api/client";

/** Slide-in detail for a clicked brain node: real excerpt + provenance + usage. */
export default function BrainEntryDetail({ leaf, onClose }: { leaf: BrainLeaf; onClose: () => void }) {
  const [entry, setEntry] = useState<BrainEntry | null>(null);
  useEffect(() => {
    let ok = true;
    setEntry(null);
    api.getBrainEntry(leaf.kind, leaf.ref)
      .then((e) => { if (ok) setEntry(e); })
      .catch(() => { if (ok) setEntry(null); });
    return () => { ok = false; };
  }, [leaf]);

  return (
    <div className="absolute top-0 right-0 h-full w-[360px] bg-surface-raised border-l border-border p-4 overflow-auto z-20">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[13px] font-medium text-foreground truncate">{leaf.label}</span>
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
          <div className="text-[12px] text-foreground whitespace-pre-wrap leading-relaxed">{entry.excerpt}</div>
        </>
      )}
    </div>
  );
}
