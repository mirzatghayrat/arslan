// FilterChips — shared secondary filter row inside a Capability-Library tab.
// Small rounded chips (accent when active, optional count badge) in a
// horizontally scrollable row, so a tab's groups are visible without
// vertical scrolling. Purely presentational; the parent owns the filter state.
export type FilterChip = { id: string; label: string; count?: number };

export default function FilterChips({
  chips,
  active,
  onSelect,
}: {
  chips: FilterChip[];
  active: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div role="group" className="flex items-center gap-1.5 overflow-x-auto pb-1 mb-4">
      {chips.map((c) => {
        const on = active === c.id;
        return (
          <button
            key={c.id}
            type="button"
            aria-pressed={on}
            onClick={() => onSelect(c.id)}
            className={`shrink-0 inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-[10px] font-mono uppercase tracking-wider transition-all ${
              on
                ? "bg-primary/15 border-primary/40 text-primary"
                : "bg-surface border-border text-muted-foreground hover:text-foreground hover:border-border-strong"
            }`}
          >
            <span>{c.label}</span>
            {c.count !== undefined && (
              <span
                className={`px-1.5 rounded-full text-[9px] leading-4 ${
                  on ? "bg-primary/20 text-primary" : "bg-surface-raised text-subtle-foreground"
                }`}
              >
                {c.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
