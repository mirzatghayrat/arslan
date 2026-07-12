/**
 * ModelCombobox — free-text model id input with a filtered suggestion
 * dropdown backed by the dynamic model catalog (Provider P2).
 *
 * Design invariant: the input is ALWAYS freely editable. A rotten/empty
 * catalog must never lock the user out — the stored value renders as-is even
 * when absent from options, and a fixed "use custom id" row always commits
 * the raw input.
 *
 * Popover idiom mirrors Select.tsx (role=listbox/option, pointerdown-outside
 * closes, ArrowUp/Down highlight, Enter commits, Escape closes).
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw } from "lucide-react";
import type { ModelInfo } from "../api/client.types";

export interface ModelComboboxProps {
  value: string;
  onChange: (v: string) => void;
  options: ModelInfo[];
  /** Small inline hint rendered under the field (stale/last-updated info). */
  staleHint?: string;
  /** When provided, a refresh button is rendered next to the input. */
  onRefresh?: () => void;
  disabled?: boolean;
  ariaLabel?: string;
  "data-testid"?: string;
}

/** 128000 → "128k", 1048576 → "1M"-ish compact context-window format. */
function formatContextWindow(cw: number): string {
  if (cw >= 1_000_000) {
    const m = cw / 1_000_000;
    return `${Number.isInteger(m) ? m : m.toFixed(1)}M`;
  }
  if (cw >= 1000) return `${Math.round(cw / 1000)}k`;
  return String(cw);
}

/** Explicit map — keeps i18n keys greppable (no dynamic key building). */
const CAP_KEYS: Record<string, string> = {
  tools: "settings.modelCapTools",
  vision: "settings.modelCapVision",
  reasoning: "settings.modelCapReasoning",
};

export default function ModelCombobox({
  value,
  onChange,
  options,
  staleHint,
  onRefresh,
  disabled = false,
  ariaLabel,
  "data-testid": dataTestId,
}: ModelComboboxProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  /** null = not editing; input displays `value`. Non-null = in-progress text. */
  const [draft, setDraft] = useState<string | null>(null);
  /** Index into [ ...filtered, customRow ]; -1 = none highlighted. */
  const [highlighted, setHighlighted] = useState(-1);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Refs so the outside-click listener sees current values without re-binding.
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const valueRef = useRef(value);
  valueRef.current = value;

  const displayValue = draft ?? value;

  // Show ALL options until the user actually edits (standard combobox UX:
  // click-to-browse); once typing, filter by substring on id + display_name.
  const filtered = useMemo(() => {
    if (draft === null) return options;
    const q = draft.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) =>
        o.id.toLowerCase().includes(q) ||
        (o.display_name ?? "").toLowerCase().includes(q),
    );
  }, [draft, options]);

  // Total highlightable rows = filtered options + the fixed custom-id row.
  const rowCount = filtered.length + 1;

  const close = useCallback(() => {
    setOpen(false);
    setHighlighted(-1);
  }, []);

  const commit = useCallback(
    (v: string) => {
      onChange(v);
      setDraft(null);
      close();
    },
    [onChange, close],
  );

  // ── click-outside: close; commit pending free text (blur-save semantics) ──
  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (e: PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        const pending = draftRef.current;
        if (pending !== null && pending !== valueRef.current) {
          onChange(pending);
        }
        setDraft(null);
        close();
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open, close, onChange]);

  // ── keyboard ──────────────────────────────────────────────────────────────
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) {
          setOpen(true);
          setHighlighted(0);
        } else {
          setHighlighted((prev) => Math.min(prev + 1, rowCount - 1));
        }
        break;
      case "ArrowUp":
        e.preventDefault();
        if (open) setHighlighted((prev) => Math.max(prev - 1, -1));
        break;
      case "Enter":
        e.preventDefault();
        if (open && highlighted >= 0 && highlighted < filtered.length) {
          commit(filtered[highlighted].id);
        } else {
          // No highlight (or custom row highlighted): commit the raw input.
          commit(displayValue);
        }
        break;
      case "Escape":
        e.preventDefault();
        setDraft(null); // revert uncommitted text
        close();
        break;
      default:
        break;
    }
  };

  const listboxId = dataTestId ? `${dataTestId}-listbox` : undefined;

  return (
    <div ref={containerRef} className="relative w-full">
      <div className="flex items-center gap-1.5">
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-label={ariaLabel}
          data-testid={dataTestId}
          disabled={disabled}
          value={displayValue}
          onFocus={() => {
            if (!disabled) setOpen(true);
          }}
          onChange={(e) => {
            setDraft(e.target.value);
            setOpen(true);
            setHighlighted(-1);
          }}
          onKeyDown={handleKeyDown}
          className={[
            "w-full bg-background border rounded-xl px-3 py-2",
            "text-xs font-mono text-foreground placeholder-subtle-foreground",
            "focus:outline-none focus:border-primary focus:ring-1 focus:ring-ring",
            "transition-all",
            open ? "border-primary ring-1 ring-ring" : "border-border-strong",
            disabled ? "opacity-50 cursor-not-allowed" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        />
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            disabled={disabled}
            aria-label={t("settings.modelRefresh")}
            title={t("settings.modelRefresh")}
            className="flex-shrink-0 p-2 text-subtle-foreground hover:text-primary border border-border hover:border-primary/50 rounded-xl transition-colors disabled:opacity-50"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* Suggestion panel */}
      {open && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          className={[
            "absolute z-50 left-0 right-0 mt-1",
            "bg-surface border border-border rounded-xl shadow-lg",
            "overflow-hidden max-h-64 overflow-y-auto",
            "animate-select-open",
          ].join(" ")}
          style={{
            animationDuration: "120ms",
            animationTimingFunction: "cubic-bezier(0.16, 1, 0.3, 1)",
            animationFillMode: "both",
          }}
        >
          {filtered.map((opt, idx) => {
            const isSelected = opt.id === value;
            const isHighlighted = idx === highlighted;
            const caps = opt.capabilities.filter((c) => CAP_KEYS[c]);
            return (
              <li
                key={opt.id}
                role="option"
                aria-selected={isSelected}
                onPointerDown={(e) => {
                  // Prevent input blur before the commit lands.
                  e.preventDefault();
                  commit(opt.id);
                }}
                onMouseEnter={() => setHighlighted(idx)}
                className={[
                  "flex items-center justify-between gap-2 px-3 py-2",
                  "text-xs font-mono select-none cursor-pointer",
                  "transition-colors duration-75",
                  isHighlighted && !isSelected ? "bg-surface-raised text-foreground" : "",
                  isSelected ? "text-primary bg-primary/10" : "text-foreground",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                <span className="truncate min-w-0">
                  {opt.id}
                  {opt.display_name && opt.display_name !== opt.id && (
                    <span className="ml-2 text-[10px] text-subtle-foreground font-sans">
                      {opt.display_name}
                    </span>
                  )}
                </span>
                <span className="flex items-center gap-1 flex-shrink-0">
                  {caps.map((cap) => (
                    <span
                      key={cap}
                      className="px-1 py-0.5 text-[9px] font-mono rounded bg-primary/10 text-primary border border-primary/20"
                    >
                      {t(CAP_KEYS[cap])}
                    </span>
                  ))}
                  {opt.context_window != null && (
                    <span className="text-[9px] font-mono text-subtle-foreground">
                      {formatContextWindow(opt.context_window)}
                    </span>
                  )}
                </span>
              </li>
            );
          })}

          {/* Fixed last row: commit the raw input as a custom model id */}
          <li
            role="option"
            aria-selected={false}
            data-testid="model-custom-id-row"
            onPointerDown={(e) => {
              e.preventDefault();
              commit(displayValue);
            }}
            onMouseEnter={() => setHighlighted(filtered.length)}
            className={[
              "flex items-center gap-2 px-3 py-2",
              "text-xs font-mono select-none cursor-pointer",
              "border-t border-border/60 text-muted-foreground",
              "transition-colors duration-75",
              highlighted === filtered.length ? "bg-surface-raised text-foreground" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {t("settings.modelCustomId", { id: displayValue })}
          </li>
        </ul>
      )}

      {/* Inline stale hint under the field */}
      {staleHint && (
        <p className="mt-1 text-[10px] font-mono text-subtle-foreground">{staleHint}</p>
      )}
    </div>
  );
}
