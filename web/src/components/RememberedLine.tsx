import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { RememberedFact } from "../api/client.types";
import { request } from "../api/client";
import { openSection } from "../lib/sections";

/** Facts are stored about "the user" for the model; to the user they read as "you".
 *  Only where it is a clean swap (Chinese, Japanese): English "The user prefers" →
 *  "You prefers" would be worse than leaving it, so other languages stay as written. */
export function toUser(text: string): string {
  // "yong hu" -> "ni" (zh), "yuuzaa wa" -> "anata wa" (ja); escaped: no CJK literals in components.
  return text.replace(/^\u7528\u6237(?=[^\s])/, "\u4f60").replace(/^\u30e6\u30fc\u30b6\u30fc\u306f/, "\u3042\u306a\u305f\u306f");
}

/** D1 (0.1.55): what Arslan remembered after a turn — ONE quiet line, never a reply.
 *  "Remembered: A · B [Undo]" for facts that took effect; "Arslan would like to remember: …
 *  [Review in Memory]" for the ones that wait (sensitive, or "remember me" off). Undo deletes exactly the
 *  entries this turn created, at the version they were created with. */
export default function RememberedLine({ facts }: { facts: RememberedFact[] }) {
  const { t } = useTranslation();
  const [state, setState] = useState<"idle" | "busy" | "undone" | "changed">("idle");
  const active = facts.filter((f) => f.status === "active");
  const waiting = facts.filter((f) => f.status === "proposed");
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

  const link = "ml-2 underline underline-offset-2 hover:text-foreground disabled:opacity-50";
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
      {waiting.length > 0 && <p>
        <span>{t("chat.wantsToRemember", { text: join(waiting) })}</span>
        <button type="button" className={link} onClick={() => openSection("brain")}>{t("chat.rememberedReview")}</button>
      </p>}
    </div>
  );
}
