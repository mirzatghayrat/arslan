import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { GraphNodeDto } from "../../api/client";
import { MAX_CHAIN, chainOf, indexById, supersededAt } from "./temporal";

interface Props {
  /** node id of the selected entry, e.g. "fact:7" */
  selectedId: string | null;
  nodes: GraphNodeDto[];
  onPickId: (id: string) => void;
  className?: string;
}

/**
 * F1 — the genealogy of one belief: what it replaced, and what replaced it.
 *
 * Renders nothing unless the selection actually has a supersede relation, so it never
 * occupies space to say "no history".
 *
 * 🔴 Every 「至」 instant here is DERIVED from the successor's valid_from, never
 * recorded (there is no superseded_at column). When it cannot be trusted — successor
 * missing, its valid_from null, or it predating what it replaced — supersededAt returns
 * null and this renders 未知 as a word. It must never fall back to "now" or to the
 * successor's row time; a plausible wrong instant is worse than an honest gap, because
 * nothing downstream could tell them apart.
 */
export default function BrainLineage({ selectedId, nodes, onPickId, className }: Props) {
  const { t } = useTranslation();

  const chain = useMemo(
    () => (selectedId ? chainOf(selectedId, nodes) : []),
    [selectedId, nodes],
  );
  const byId = useMemo(() => indexById(nodes), [nodes]);

  if (chain.length < 2) return null;

  return (
    <div className={className} data-testid="brain-lineage">
      <div className="mb-1 text-[11px] text-subtle-foreground">
        {t("brain.temporal.lineage")}
      </div>
      <ol className="space-y-1">
        {chain.map((id, i) => {
          const n = byId.get(id);
          const end = n ? supersededAt(n, byId) : null;
          const current = n?.superseded_by == null;
          return (
            <li key={id} data-lineage-id={id} data-current={current ? "true" : undefined}>
              <button
                className={`w-full truncate rounded px-1.5 py-1 text-left text-[11px] ${
                  id === selectedId ? "bg-surface-raised" : ""
                } ${current ? "text-foreground" : "text-subtle-foreground"}`}
                onClick={() => onPickId(id)}
              >
                <span className="mr-1 font-mono text-[9px] opacity-60">{i + 1}</span>
                {n?.label || id}
                <span className="ml-1 font-mono text-[9px] opacity-60">
                  {n?.valid_from ? n.valid_from.slice(0, 10) : t("brain.temporal.validFromAlways")}
                  {!current && ` → ${end ? end.slice(0, 10) : t("brain.temporal.endUnknown")}`}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {chain.length >= MAX_CHAIN && (
        <div className="mt-1 text-[10px] text-warning" data-testid="lineage-truncated">
          {t("brain.temporal.lineageTruncated", { n: MAX_CHAIN })}
        </div>
      )}
    </div>
  );
}
