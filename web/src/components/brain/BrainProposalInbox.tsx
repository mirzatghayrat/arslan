import { useCallback, useEffect, useState } from "react";
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

  if (rows == null) {
    return <div className="brain-inbox brain-inbox--msg" data-testid="proposal-inbox">…</div>;
  }

  return (
    <div className="brain-inbox" data-testid="proposal-inbox">
      {error && <div className="brain-inbox__error" role="alert">{error}</div>}

      {rows.length === 0 ? (
        <div className="brain-inbox__empty" data-testid="inbox-empty">
          {t("brain.inbox.empty")}
        </div>
      ) : (
        rows.map((p) => {
          const destructive = isDestructive(p);
          const rowsDiff = lineDiff(beforeText(p), afterText(p));
          return (
            <div key={p.id} className="brain-inbox__row" data-testid="proposal-row"
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
