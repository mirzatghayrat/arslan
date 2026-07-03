import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { CATEGORIES, type OrreryNodeIn, type OrreryEdgeIn } from './orreryLayout';

interface Props {
  node: OrreryNodeIn;
  nodes: OrreryNodeIn[];
  edges: OrreryEdgeIn[];
  onSelect: (node: OrreryNodeIn | null) => void;
}

// Human label for a node category (hub has no CATEGORIES entry).
function catLabel(cat: string): string {
  if (cat === 'hub') return 'YOU';
  return CATEGORIES.find((c) => c.key === cat)?.label ?? cat;
}

/**
 * Slide-in detail panel for a selected orrery node. Shows the node's category,
 * label, meta, and its direct neighbours (derived from `edges`). Clicking a
 * neighbour selects it, letting the user traverse the graph from the panel.
 */
export default function OrreryDetailPanel({ node, nodes, edges, onSelect }: Props) {
  const { t } = useTranslation();

  // Direct neighbours: any node sharing an edge with the selected node.
  const neighborIds = new Set<string>();
  for (const e of edges) {
    if (e.a === node.id) neighborIds.add(e.b);
    else if (e.b === node.id) neighborIds.add(e.a);
  }
  const neighbors = nodes.filter((n) => neighborIds.has(n.id));

  return (
    <aside className="w-80 border-l border-border bg-sidebar/95 backdrop-blur-xl flex flex-col h-full select-none relative z-20 animate-slide-in-right overflow-y-auto">
      {/* Header */}
      <div className="p-5 border-b border-border/50 flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <span className="text-[9px] font-mono uppercase tracking-widest text-primary font-bold">
            {catLabel(node.cat)}
          </span>
          <h3 className="text-sm font-sans font-semibold text-foreground leading-snug break-words">
            {node.label}
          </h3>
          {node.meta && (
            <p className="text-[11px] font-mono text-muted-foreground break-words">{node.meta}</p>
          )}
        </div>
        <button
          onClick={() => onSelect(null)}
          className="text-muted-foreground hover:text-foreground transition-colors shrink-0"
          aria-label={t('common.close')}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Connections */}
      <div className="p-5 space-y-3 flex-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-mono text-foreground uppercase tracking-widest font-bold">
            {t('brain.connections')}
          </span>
          <span className="text-[9px] font-mono text-primary bg-primary/10 rounded px-2 py-0.5 font-bold">
            {neighbors.length}
          </span>
        </div>

        {neighbors.length === 0 ? (
          <p className="text-[10px] font-mono text-subtle-foreground italic">
            {t('brain.noConnections')}
          </p>
        ) : (
          <div className="space-y-1.5">
            {neighbors.map((n) => (
              <button
                key={n.id}
                onClick={() => onSelect(n)}
                className="w-full text-left p-2.5 rounded-xl bg-background/60 border border-border/50 hover:border-primary/40 hover:bg-primary/[0.04] transition-all group"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-sans text-foreground group-hover:text-primary transition-colors truncate">
                    {n.label}
                  </span>
                  <span className="text-[8px] font-mono uppercase tracking-wider text-subtle-foreground shrink-0">
                    {catLabel(n.cat)}
                  </span>
                </div>
                {n.meta && (
                  <div className="text-[9px] font-mono text-subtle-foreground mt-0.5 truncate">
                    {n.meta}
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
