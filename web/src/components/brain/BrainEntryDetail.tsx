import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { factCategoryLabel } from "./catLabel";
import { X } from "lucide-react";
import { ApiError, api, type BrainEntry, type BrainLeaf } from "../../api/client";

/** Slide-in detail for a clicked brain node: real excerpt + provenance + usage.
 *
 * F0.5 wires up three payload fields the backend has emitted since the P1/D rounds and
 * that NO brain component read until now: `sensitive`, `provenance_record` and
 * `superseded_by` (the last one gating the undo affordance).
 */
export default function BrainEntryDetail(
  { leaf, onClose, onChanged, children }: {
    leaf: BrainLeaf; onClose: () => void; onChanged?: () => void;
    /** F1 — rendered after the excerpt, INSIDE this panel. It has to be a child rather
     * than a sibling: this component's root is absolutely positioned, full height and
     * opaque, so any sibling in a shared absolute wrapper is painted underneath it. */
    children?: React.ReactNode;
  },
) {
  const { t } = useTranslation();
  const [entry, setEntry] = useState<BrainEntry | null>(null);
  // 🔴 "not loaded yet" and "failed to load" used to be the SAME state (null), so a 404
  // rendered "loading…" forever with no error — the exact defect this round fixed in the
  // index-health strip, left in place here until the final review pointed at it. It
  // matters more now: the activity strip can hold a row for an entity that has since
  // been DELETED (nothing purges brain_usage_events on delete), so clicking one is a
  // reachable 404, not a hypothetical.
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [undoing, setUndoing] = useState(false);
  const [undoErr, setUndoErr] = useState<string | null>(null);
  /** invalidates the in-flight fetch. `load()` is called from two places — the effect and
   * undo() — and only the effect wired up its cancellation, so a late response for the
   * previous leaf could overwrite the current one. */
  const alive = useRef({ ok: true });

  const load = () => {
    alive.current.ok = false;
    const token = { ok: true };
    alive.current = token;
    setEntry(null);
    setLoadErr(null);
    api.getBrainEntry(leaf.kind, leaf.ref)
      .then((e) => { if (token.ok) setEntry(e); })
      .catch((e) => {
        if (!token.ok) return;
        setEntry(null);
        setLoadErr(
          e instanceof ApiError && e.status === 404
            ? t("brain.entry_gone")
            : t("brain.read_failed"),
        );
      });
    return () => { token.ok = false; };
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
    <div data-testid="brain-entry-detail"
      className="absolute top-0 right-0 h-full w-[360px] bg-surface-raised border-l border-border p-4 overflow-auto z-20">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[13px] font-medium text-foreground truncate">
          {entry?.sensitive && (
            <span title={t("brain.sensitive")} data-testid="entry-sensitive" className="mr-1">🔒</span>
          )}
          {leaf.label}
        </span>
        <button onClick={onClose} aria-label={t("brain.close_detail")} className="text-subtle-foreground hover:text-foreground">
          <X className="w-4 h-4" />
        </button>
      </div>
      {loadErr ? (
        <div className="text-[11px] text-warning" role="alert" data-testid="entry-load-error">
          {loadErr}
        </div>
      ) : entry == null ? (
        <div className="text-[11px] text-subtle-foreground">loading…</div>
      ) : (
        <>
          <div className="text-[10.5px] text-subtle-foreground font-mono mb-2">
            {(() => {
              // fact provenance is "<category-key> · <source>" (server contract,
              // see brain.py brain_entry); translate the key half, pass through
              // learning/material shapes untouched.
              const prov = entry.provenance ?? "";
              const [head, ...rest] = prov.split(" · ");
              return rest.length ? [factCategoryLabel(t, head), ...rest].join(" · ") : prov;
            })()}
            {t("brain.used_n_dot", { n: entry.usage_count })}
            {entry.last_used_ref ? t("brain.last_used_for", { ref: entry.last_used_ref }) : ""}
          </div>

          {/* F1 — valid_from has been on this payload since P1 and nothing rendered it.
              A belief with no recorded start is 自古有效 (models.py:148), which is a
              real state and not a missing value, so it is spelled out rather than
              blanked. */}
          <div className="mb-2 text-[10.5px] text-subtle-foreground" data-testid="entry-valid-from">
            {t("brain.temporal.validFrom")}
            {": "}
            {entry.valid_from
              ? entry.valid_from.slice(0, 10)
              : t("brain.temporal.validFromAlways")}
          </div>

          {entry.superseded_by != null && (
            <div className="mb-2 text-[11px] text-warning" data-testid="entry-superseded">
              {t("brain.superseded_by_line", { id: entry.superseded_by })}
              {/* 🔴 The END of a belief is DERIVED from its successor's valid_from and
                  is not available here (this panel fetches one entry). Rather than
                  show a number that might be wrong, say nothing about when — the
                  genealogy panel, which has the whole node set, is where the derived
                  instant (or 未知) is shown. */}
              {canUndo && (
                <button className="ml-2 underline disabled:opacity-50" disabled={undoing}
                  onClick={() => void undo()} data-testid="undo-supersede">
                  {undoing ? t("brain.undoing") : t("brain.undo_supersede")}
                </button>
              )}
            </div>
          )}
          {undoErr && <div className="mb-2 text-[11px] text-danger" role="alert">{undoErr}</div>}

          {entry.sensitive && (
            <div className="mb-2 text-[10.5px] text-subtle-foreground" data-testid="sensitive-note">
              {t("brain.sensitive_note")}
            </div>
          )}

          <div className="text-[12px] text-foreground whitespace-pre-wrap leading-relaxed">{entry.excerpt}</div>

          {entry.provenance_record && Object.keys(entry.provenance_record).length > 0 && (
            <details className="mt-3 text-[10.5px] text-subtle-foreground" data-testid="provenance-record">
              <summary className="cursor-pointer">{t("brain.provenance")}</summary>
              <pre className="mt-1 whitespace-pre-wrap break-all font-mono">
                {JSON.stringify(entry.provenance_record, null, 2)}
              </pre>
            </details>
          )}

          {children}
        </>
      )}
    </div>
  );
}
