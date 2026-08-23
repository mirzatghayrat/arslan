import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type MemoryProposalDto } from "../../api/client";
import { lineDiff } from "../../lib/lineDiff";

/** F2 — the Tier-2 human gate for memory proposals.
 *
 * 🔴 ACCEPT IS NOT UNIFORMLY SAFE, and the UI must not pretend it is. Of the five kinds:
 *
 *   supersede_suspect / edit_high_conf_suspect  reversible — they flip a `superseded_by`
 *     pointer, and POST /brain/undo-supersede can put it back.
 *   delete_suspect                              a real DELETE of the row (plus its FTS
 *     entry), or — on `spawns` — wiping the ENTIRE memory_facts array, which is the only
 *     granularity that column supports. Nothing can undo either.
 *   preference_overwrite_suspect                whole-array replace; the old array is gone.
 *
 * So the destructive three are excluded from the fast path. A blanket keyboard triage
 * over a mixed-kind inbox would destroy data on one mis-keystroke, and "it was one
 * keystroke" is not a story a user can act on afterwards.
 *
 * KEYBOARD TRIAGE (F2): J/K (and the arrows) move, 1 accepts, 3 dismisses, Escape backs
 * out of a confirm. On a destructive row 1 does NOT accept — it opens the same confirm
 * the mouse path opens, so the one-keystroke hazard above cannot happen through this
 * door either.
 *
 * TWO KEYS FROM THE BRIEF ARE DELIBERATELY ABSENT, because the things they act on do not
 * exist: `2` was "approve after editing" and this panel has no edit affordance, and `H`
 * was "hold", which is not a state the proposal API has (pending / accepted / dismissed).
 * Binding either would mean inventing a behaviour and calling it a shortcut.
 */
const REVERSIBLE_KINDS = new Set(["supersede_suspect", "edit_high_conf_suspect"]);

function isDestructive(p: MemoryProposalDto): boolean {
  return !REVERSIBLE_KINDS.has(p.kind);
}

/** The "after" value, which lives in a different place per kind: a materialized row for
 * supersede, and inside `provenance` for everything the agent proposed but never wrote. */
function afterText(p: MemoryProposalDto): string {
  const prov = (p.provenance ?? {}) as Record<string, unknown>;
  if (Array.isArray(prov.new_array)) return (prov.new_array as string[]).join("\n");
  if (typeof prov.content === "string") return prov.content;
  return p.new_excerpt ?? "";
}

function beforeText(p: MemoryProposalDto): string {
  const prov = (p.provenance ?? {}) as Record<string, unknown>;
  // For a preference overwrite the honest "before" is what the proposal was DERIVED from,
  // not the live value: they differ exactly when someone else changed the spawn since,
  // and that is the case the server answers 409 for.
  if (Array.isArray(prov.based_on)) return (prov.based_on as string[]).join("\n");
  return p.old_excerpt ?? "";
}

export default function BrainProposalInbox({ onChanged }: { onChanged?: () => void }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<MemoryProposalDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  // Roving focus for the keyboard path. An INDEX, not an id: after an action the
  // list refetches and the row is gone, and staying at the same position is what
  // triage feels like — following the id would jump the user somewhere else.
  const [cursor, setCursor] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await api.listMemoryProposals({ status: "pending" }));
    } catch (e) {
      setRows([]);
      setError(String(e));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const act = async (p: MemoryProposalDto, accept: boolean) => {
    setBusy(p.id);
    setError(null);
    try {
      if (accept) await api.acceptMemoryProposal(p.id);
      else await api.dismissMemoryProposal(p.id);
      setConfirming(null);
      // 🔴 REFETCH, never patch. Accepting auto-dismisses sibling proposals server-side
      // with nothing in the response to say so, and the action responses omit the
      // excerpt fields the list carries.
      await load();
      onChanged?.();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  // The cursor is clamped where it is READ (both in the key handler and in the
  // row rendering), so a list that shrinks under a stale index needs no effect to
  // correct it — and there was one here until a mutation showed that deleting it
  // changed nothing. Two clamps expressing one rule, with only one of them doing
  // any work, is worse than one: the dead half reads as load-bearing.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!rows || rows.length === 0) return;
    const p = rows[Math.min(cursor, rows.length - 1)];
    const move = (delta: number) => {
      e.preventDefault();
      setCursor((c) => Math.min(rows.length - 1, Math.max(0, c + delta)));
    };
    switch (e.key) {
      case "j": case "J": case "ArrowDown": return move(1);
      case "k": case "K": case "ArrowUp": return move(-1);
      case "Escape":
        // Only meaningful mid-confirm; harmless otherwise.
        if (confirming !== null) { e.preventDefault(); setConfirming(null); }
        return;
      case "1":
        e.preventDefault();
        if (busy !== null) return;
        // The destructive branch takes the SAME door as the mouse: open the
        // confirm, do not act. A second `1` still will not accept — only the
        // confirm button does — so no repeat-key sequence can delete anything.
        if (isDestructive(p)) setConfirming(p.id);
        else void act(p, true);
        return;
      case "3":
        e.preventDefault();
        if (busy === null) void act(p, false);
        return;
      default:
    }
  };

  if (rows == null) {
    return <div className="brain-inbox brain-inbox--msg" data-testid="proposal-inbox">…</div>;
  }

  return (
    <div
      className="brain-inbox"
      data-testid="proposal-inbox"
      ref={listRef}
      // The list itself takes focus and owns the keys, rather than each row: a
      // roving tabindex would put every proposal in the Tab order, and Tab
      // through forty of them is not triage.
      tabIndex={0}
      role="listbox"
      aria-label={t("brain.inbox.aria_list")}
      onKeyDown={onKeyDown}
    >
      {error && <div className="brain-inbox__error" role="alert">{error}</div>}
      {rows.length > 0 && (
        <p className="brain-inbox__keyhint" data-testid="inbox-keyhint">
          {t("brain.inbox.keyhint")}
        </p>
      )}

      {rows.length === 0 ? (
        <div className="brain-inbox__empty" data-testid="inbox-empty">
          {t("brain.inbox.empty")}
        </div>
      ) : (
        rows.map((p, i) => {
          const destructive = isDestructive(p);
          const rowsDiff = lineDiff(beforeText(p), afterText(p));
          const atCursor = i === Math.min(cursor, rows.length - 1);
          return (
            <div key={p.id}
              className={`brain-inbox__row${atCursor ? " is-cursor" : ""}`}
              data-testid="proposal-row"
              role="option"
              aria-selected={atCursor}
              data-cursor={atCursor ? "1" : undefined}
              onMouseEnter={() => setCursor(i)}
              data-kind={p.kind} data-destructive={destructive ? "1" : undefined}>
              <div className="brain-inbox__head">
                <span className="brain-inbox__kind">{t(`brain.inbox.kind.${p.kind}`)}</span>
                {destructive && (
                  <span className="brain-inbox__danger" data-testid="destructive-badge">
                    {t("brain.inbox.irreversible")}
                  </span>
                )}
                {p.reason && <span className="brain-inbox__reason">{p.reason}</span>}
              </div>

              <pre className="brain-inbox__diff">
                {rowsDiff.map((r, i) => (
                  <div key={i} data-diff={r.type}>{r.text}</div>
                ))}
              </pre>

              <div className="brain-inbox__actions">
                <button type="button" disabled={busy === p.id}
                  onClick={() => void act(p, false)} data-testid="dismiss-btn">
                  {t("brain.inbox.dismiss")}
                </button>

                {destructive ? (
                  confirming === p.id ? (
                    <>
                      <span className="brain-inbox__danger" data-testid="confirm-prompt">
                        {t("brain.inbox.confirm_irreversible")}
                      </span>
                      <button type="button" className="brain-inbox__danger-btn"
                        disabled={busy === p.id} onClick={() => void act(p, true)}
                        data-testid="confirm-accept-btn">
                        {t("brain.inbox.confirm_yes")}
                      </button>
                      <button type="button" onClick={() => setConfirming(null)}
                        data-testid="confirm-cancel-btn">
                        {t("brain.inbox.confirm_no")}
                      </button>
                    </>
                  ) : (
                    <button type="button" disabled={busy === p.id}
                      onClick={() => setConfirming(p.id)} data-testid="accept-destructive-btn">
                      {t("brain.inbox.accept")}
                    </button>
                  )
                ) : (
                  <button type="button" disabled={busy === p.id}
                    onClick={() => void act(p, true)} data-testid="accept-btn">
                    {t("brain.inbox.accept")}
                  </button>
                )}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
