type Tab = { id: string; label: string };
export default function CapabilityTabs({ active, onChange, tabs }:
  { active: string; onChange: (id: string) => void; tabs: Tab[] }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-border/50 mb-5">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={active === t.id}
          onClick={() => onChange(t.id)}
          className={`px-4 py-2 text-xs font-mono uppercase tracking-wider transition-all border-b-2 -mb-px ${
            active === t.id
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
