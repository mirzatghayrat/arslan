type Tab = { id: string; label: string };
export default function CapabilityTabs({ active, onChange, tabs }:
  { active: string; onChange: (id: string) => void; tabs: Tab[] }) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-border/50 mb-5">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={active === t.id}
          tabIndex={active === t.id ? 0 : -1}
          onKeyDown={event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const index = tabs.findIndex(tab => tab.id === t.id);
            const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
              : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
            onChange(tabs[next].id);
            event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
          }}
          onClick={() => onChange(t.id)}
          className={`shrink-0 px-4 py-2 text-xs font-sans transition-all border-b-2 -mb-px ${
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
