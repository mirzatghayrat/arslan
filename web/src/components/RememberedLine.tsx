import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { RememberedFact } from "../api/client.types";
import { request } from "../api/client";
import { companionApi } from "../api/companion";
import { openSection } from "../lib/sections";

/** Facts are stored about "the user" for the model; to the user they read as "you".
 *  Only where it is a clean swap (Chinese, Japanese): English "The user prefers" →
 *  "You prefers" would be worse than leaving it, so other languages stay as written. */
export function toUser(text: string): string {
  // "yong hu" -> "ni" (zh), "yuuzaa wa" -> "anata wa" (ja); escaped: no CJK literals in components.
  return text.replace(/^\u7528\u6237(?=[^\s])/, "\u4f60").replace(/^\u30e6\u30fc\u30b6\u30fc\u306f/, "\u3042\u306a\u305f\u306f");
}

type Asked = RememberedFact & { proposalId: number };

const WHY = new Set(["external_seen", "not_present", "sensitive", "confirmation_required"]);
/** Why one waits, as the line says it. A frame from before INB2 names no reason. */
const whyOf = (f: RememberedFact) => (f.reason && WHY.has(f.reason) ? f.reason : f.sensitive ? "sensitive" : "confirmation_required");

const link = "ml-2 underline underline-offset-2 hover:text-foreground disabled:opacity-50";

/** D1 (0.1.55): what Arslan remembered after a turn — quiet lines, never a reply. "Remembered: A · B [Undo]"
 *  for facts that took effect; Undo deletes exactly the entries this turn created, at the version they were
 *  created with. INB2 (v0.1.64): a sensitive one from the user's own present, clean turn asks once, with two
 *  buttons bound to its proposal; any other that waits says why and points to Memory's "To sort" list. */
export default function RememberedLine({ facts }: { facts: RememberedFact[] }) {
  const { t } = useTranslation();
  const [state, setState] = useState<"idle" | "busy" | "undone" | "changed">("idle");
  const active = facts.filter((f) => f.status === "active");
  const asks = facts.filter((f): f is Asked => f.status === "proposed" && f.reason === "sensitive" && f.proposalId != null);
  const waiting = facts.filter((f) => f.status === "proposed" && !asks.includes(f as Asked));
  const undoable = active.filter((f) => f.entryId && f.version);

  async function undo() {
    setState("busy");
    try {
      for (const f of undoable) {
        await request(`/memory/entries/${encodeURIComponent(f.entryId!)}?expected_version=${f.version}`,
          { method: "DELETE" });
      }
      setState("undone");
    } catch {
      setState("changed");
    }
  }

  const join = (list: RememberedFact[]) => list.map((f) => toUser(f.content)).join(" · ");
  return (
    <div data-testid="remembered-line" className="py-0.5 text-center text-[11px] text-muted-foreground">
      {active.length > 0 && <p>
        <span>{t("chat.remembered", { text: join(active) })}</span>
        {state === "undone" ? <span className="ml-2">{t("chat.rememberedUndone")}</span>
          : state === "changed" ? <button type="button" className={link} onClick={() => openSection("brain")}>{t("chat.rememberedChanged")}</button>
          : undoable.length > 0 && <button type="button" className={link} disabled={state === "busy"}
              onClick={() => void undo()}>{t("chat.rememberedUndo")}</button>}
      </p>}
      {asks.map((f) => <Ask key={f.proposalId} fact={f} />)}
      {[...new Set(waiting.map(whyOf))].map((why) => <p key={why} data-testid="memory-waits">
        <span>{t("chat.memoryWaits", { text: join(waiting.filter((f) => whyOf(f) === why)), reason: t(`chat.memoryWhy_${why}`) })}</span>
        <button type="button" className={link} onClick={() => openSection("brain")}>{t("chat.memorySeeInMemory")}</button>
      </p>)}
    </div>
  );
}

/** INB2: the one question about a sensitive entry. Both buttons answer exactly this proposal, at the version
 *  the line showed; the server refuses one already answered (in Memory, say) or whose entry changed since,
 *  and then the line points to Memory. Kept means kept for this Mac only, the sensitivity
 *  acknowledged, as "Keep, this Mac only" in "To sort". It is never asked again: unanswered, it waits there. */
function Ask({ fact }: { fact: Asked }) {
  const { t } = useTranslation();
  const [state, setState] = useState<"ask" | "busy" | "kept" | "skipped" | "changed">("ask");

  async function answer(keep: boolean) {
    setState("busy");
    try {
      await companionApi.resolveProposal(fact.proposalId, keep, keep, false, fact.version ?? undefined);
      setState(keep ? "kept" : "skipped");
    } catch {
      setState("changed");
    }
  }

  const text = toUser(fact.content);
  return (
    <p data-testid={`memory-ask-${fact.proposalId}`}>
      {state === "kept" ? t("chat.memoryKeptLocal", { text }) : state === "skipped" ? t("chat.memorySkipped") : <>
        <span>{t("chat.memoryAsk", { text })}</span>
        {state === "changed" ? <button type="button" className={link} onClick={() => openSection("brain")}>{t("chat.rememberedChanged")}</button> : <>
          <button type="button" disabled={state === "busy"} onClick={() => void answer(true)}
            className="ml-2 rounded-md border border-border px-2 py-0.5 text-foreground hover:bg-fill disabled:opacity-50">{t("pendingMemory.keepLocal")}</button>
          <button type="button" className={link} disabled={state === "busy"} onClick={() => void answer(false)}>{t("pendingMemory.drop")}</button>
        </>}
      </>}
    </p>
  );
}
