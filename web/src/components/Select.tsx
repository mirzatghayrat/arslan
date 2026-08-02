/**
 * Select — themed custom dropdown that replaces native <select> elements.
 *
 * Fully styled via semantic tokens (no raw hex / Tailwind color-scale classes).
 * Keyboard: Enter/Space/ArrowDown open; ArrowUp/ArrowDown move highlight;
 *           Enter confirms; Escape closes; click-outside closes.
 * ARIA: trigger aria-haspopup="listbox" + aria-expanded; panel role="listbox";
 *       options role="option" + aria-selected.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import { useDismissable } from "../hooks/useDismissable";
import AnchoredPortal from "./AnchoredPortal";

export interface SelectOption {
  value: string;
  label: string;
  /** When true the option is shown but cannot be selected (greyed, not clickable). */
  disabled?: boolean;
}

export interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  id?: string;
  ariaLabel?: string;
}

export default function Select({
  value,
  onChange,
  options,
  placeholder = "Select…",
  disabled = false,
  className = "",
  id,
  ariaLabel,
}: SelectProps) {
  const [open, setOpen] = useState(false);
  // highlighted index when navigating with keyboard (-1 = none)
  const [highlightedIndex, setHighlightedIndex] = useState<number>(-1);

  const triggerRef = useRef<HTMLButtonElement>(null);

  const selectedLabel =
    options.find((o) => o.value === value)?.label ?? placeholder;

  // ── open / close helpers ────────────────────────────────────────────────

  const openPanel = useCallback(() => {
    if (disabled) return;
    const idx = options.findIndex((o) => o.value === value);
    // Start highlight on the current value, or first non-disabled option
    const fallback = options.findIndex((o) => !o.disabled);
    setHighlightedIndex(idx >= 0 ? idx : fallback >= 0 ? fallback : 0);
    setOpen(true);
  }, [disabled, options, value]);

  const closePanel = useCallback(() => {
    setOpen(false);
    setHighlightedIndex(-1);
  }, []);

  const togglePanel = useCallback(() => {
    if (open) {
      closePanel();
    } else {
      openPanel();
    }
  }, [open, openPanel, closePanel]);

  // ── click-outside ───────────────────────────────────────────────────────

  // Class fix (floating-element sweep). Two changes, one visible and one not:
  //  · the panel is PORTALLED, because `absolute` inside Settings'
  //    `overflow-y-auto` (SettingsScreen) and Diagnostics' `overflow-auto`
  //    clipped it at every one of this component's ten call sites;
  //  · Escape becomes DOCUMENT-level. It used to live on the trigger's own
  //    onKeyDown, so it worked only while the trigger still held focus —
  //    move focus into the list, or click the panel, and Escape did nothing.
  const { anchorRef, floatingRef } = // floatingRef belongs to AnchoredPortal's own wrapper div, not the <ul> inside it.
  useDismissable<HTMLDivElement, HTMLDivElement>(
    open, closePanel);

  // ── keyboard handling on the trigger ───────────────────────────────────

  const handleTriggerKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    switch (e.key) {
      case "Enter":
      case " ":
        e.preventDefault();
        if (open && highlightedIndex >= 0) {
          // Confirm selection — skip disabled options
          const opt = options[highlightedIndex];
          if (opt && !opt.disabled) {
            onChange(opt.value);
            closePanel();
          }
        } else {
          openPanel();
        }
        break;
      case "ArrowDown":
        e.preventDefault();
        if (!open) {
          openPanel();
        } else {
          // Skip over disabled options
          setHighlightedIndex((prev) => {
            let next = prev + 1;
            while (next < options.length && options[next]?.disabled) next++;
            return next < options.length ? next : prev;
          });
        }
        break;
      case "ArrowUp":
        e.preventDefault();
        if (open) {
          setHighlightedIndex((prev) => {
            let next = prev - 1;
            while (next >= 0 && options[next]?.disabled) next--;
            return next >= 0 ? next : prev;
          });
        }
        break;
      case "Escape":
        e.preventDefault();
        closePanel();
        break;
      default:
        break;
    }
  };

  // ── option click ────────────────────────────────────────────────────────

  const handleOptionClick = (opt: SelectOption) => {
    if (opt.disabled) return;
    onChange(opt.value);
    closePanel();
    triggerRef.current?.focus();
  };

  // ── render ──────────────────────────────────────────────────────────────

  const listboxId = id ? `${id}-listbox` : undefined;

  return (
    <div ref={anchorRef} className={`relative w-full${className ? ` ${className}` : ""}`}>
      {/* Trigger */}
      <button
        ref={triggerRef}
        id={id}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={togglePanel}
        onKeyDown={handleTriggerKeyDown}
        className={[
          "w-full flex items-center justify-between gap-2",
          "bg-background border border-border-strong rounded-xl px-3 py-2",
          "text-xs font-sans text-left",
          "focus:outline-none focus:border-primary focus:ring-1 focus:ring-ring",
          "transition-all",
          open ? "border-primary ring-1 ring-ring" : "",
          disabled
            ? "opacity-50 cursor-not-allowed text-subtle-foreground"
            : "text-foreground hover:border-border-strong cursor-pointer",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <span className="truncate">{selectedLabel}</span>
        <ChevronDown
          className={[
            "w-3.5 h-3.5 flex-shrink-0 text-subtle-foreground transition-transform duration-150",
            open ? "rotate-180" : "",
          ].join(" ")}
        />
      </button>

      {/* Options panel */}
      <AnchoredPortal anchorRef={anchorRef} floatingRef={floatingRef} open={open}
                      align="left" matchAnchorWidth>
        <ul
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          className={[
            "bg-surface border border-border rounded-xl shadow-lg",
            "overflow-hidden",
            // Smooth entrance via CSS (opacity + translate)
            "animate-select-open",
          ].join(" ")}
          style={{
            // tasteful scale+fade in 120ms via inline style since Tailwind
            // @keyframes aren't guaranteed in jsdom; we declare it in JSX
            animationDuration: "120ms",
            animationTimingFunction: "cubic-bezier(0.16, 1, 0.3, 1)",
            animationFillMode: "both",
          }}
        >
          {options.map((option, idx) => {
            const isSelected = option.value === value;
            const isHighlighted = idx === highlightedIndex;
            const isDisabled = !!option.disabled;
            return (
              <li
                key={option.value}
                role="option"
                aria-selected={isSelected}
                aria-disabled={isDisabled || undefined}
                onPointerDown={(e) => {
                  // Prevent blur on the trigger
                  e.preventDefault();
                  handleOptionClick(option);
                }}
                onMouseEnter={() => !isDisabled && setHighlightedIndex(idx)}
                className={[
                  "flex items-center justify-between gap-2 px-3 py-2",
                  "text-xs font-sans select-none",
                  "transition-colors duration-75",
                  isDisabled
                    ? "opacity-40 cursor-not-allowed text-subtle-foreground"
                    : "cursor-pointer",
                  isHighlighted && !isSelected && !isDisabled
                    ? "bg-surface-raised text-foreground"
                    : "",
                  isSelected && !isDisabled
                    ? "text-primary bg-primary/10"
                    : !isDisabled ? "text-foreground" : "",
                ].join(" ")}
              >
                <span className="truncate">{option.label}</span>
                {isSelected && !isDisabled && (
                  <Check className="w-3 h-3 flex-shrink-0 text-primary" />
                )}
              </li>
            );
          })}
        </ul>
      </AnchoredPortal>
    </div>
  );
}
