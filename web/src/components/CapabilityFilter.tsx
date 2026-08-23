/**
 * "Find something I already have" — the search box on TOOLS / SKILLS / MCPS.
 *
 * Deliberately narrow. The Discover tab's box searches GitHub for things you do
 * NOT have; this one only narrows the list in front of you, and says how much
 * it hid so an empty result never reads as an empty library.
 */
import { useTranslation } from "react-i18next";
import { Search, X } from "lucide-react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  /** How many items survive the query, and how many there were. */
  shown: number;
  total: number;
  /** Distinguishes the three instances in tests and in the DOM. */
  testId: string;
  placeholder?: string;
}

export default function CapabilityFilter({
  value, onChange, shown, total, testId, placeholder,
}: Props) {
  const { t } = useTranslation();
  const active = value.trim().length > 0;
  return (
    <div className="flex items-center gap-2 mb-3">
      <div className="relative flex-1 min-w-0 max-w-md">
        <Search className="w-3 h-3 text-subtle-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          data-testid={testId}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? t("capabilities.filter.placeholder")}
          className="w-full bg-surface border border-border focus:border-primary/50 rounded-lg pl-7 pr-7 py-1.5 text-[11px] text-foreground placeholder-subtle-foreground focus:outline-none font-sans"
        />
        {active && (
          <button
            type="button"
            aria-label={t("capabilities.filter.clear")}
            data-testid={`${testId}-clear`}
            onClick={() => onChange("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-subtle-foreground hover:text-foreground"
          >
            <X className="w-3 h-3" />
          </button>
        )}
      </div>
      {active && (
        // The count is not decoration: without it, a query that hides everything
        // looks identical to having nothing installed.
        <span data-testid={`${testId}-count`}
              className="text-[10px] text-subtle-foreground font-mono whitespace-nowrap">
          {t("capabilities.filter.count", { shown, total })}
        </span>
      )}
    </div>
  );
}
