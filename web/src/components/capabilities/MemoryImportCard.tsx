import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { MemoryImportCard as Card, MemoryImportLeftOut } from "../../api/client.types";
import { AskCard, Notice, type AskQueuePosition } from "../kit";
import { Escaped, hiddenCount, isolate } from "../../lib/outsideText";
import { Row } from "./CapabilityProposeCard";

/** The summary's order, the mock's: why a line isn't a memory, then what would have repeated. */
const REASONS: MemoryImportLeftOut["reason"][] = ["one_off", "gender", "credential", "too_long", "stored", "deleted"];

/**
 * "Arslan wants to save memories" (v0.1.64 CAP8b, the mock the user approved): the lines of what the user pasted, each
 * with a tick, as plain text, with a marker for what shows nothing, since stored equals shown. The answer names ids, never
 * words, and a no or no answer stores nothing (server/services/memory_import.py). The install card's channel: answered only
 * in this window. The ticks are kept above the card, since paging re-mounts it and a line unticked must stay unticked.
 */
export default function MemoryImportCard({ card, callId, ticks, onTicks, expiresAt, queue, onConfirm, onCancel }: {
  card: Card; callId: string; ticks?: string[]; onTicks: (kept: string[]) => void;
  expiresAt?: number | null; queue?: AskQueuePosition;
  onConfirm: (callId: string, kept: string[]) => void;
  onCancel: (callId: string) => void;
}) {
  const { t } = useTranslation();
  const [kept, setKept] = useState<string[]>(ticks ?? card.entries.filter(e => e.ticked).map(e => e.id));
  const [open, setOpen] = useState(false);
  const pick = (id: string) => {
    const next = card.entries.map(e => e.id).filter(i => (i === id ? !kept.includes(i) : kept.includes(i)));
    setKept(next);
    onTicks(next);
  };
  const hidden = card.entries.reduce((n, e) => n + hiddenCount(e.text), 0);
  const parts = REASONS.flatMap(reason => {
    const count = card.left_out.filter(l => l.reason === reason).length;
    return count ? [t(`discover.import_part_${reason}`, { count })] : [];
  });
  const detail = (
    <div className="flex flex-col" data-testid="memory-import-rows">
      <Row label={t("discover.import_from")} testId="memory-import-from">{t("discover.import_fromText", { count: card.lines })}</Row>
      <Row label={t("discover.import_keeps")}>
        <span className="flex max-h-[260px] flex-col gap-[7px] overflow-auto">
          {card.entries.map(e => <label key={e.id} data-testid={`memory-import-line-${e.id}`}
            className="grid cursor-pointer grid-cols-[18px_minmax(0,1fr)] items-start gap-2">
            <input type="checkbox" checked={kept.includes(e.id)} onChange={() => pick(e.id)}
              data-testid={`memory-import-tick-${e.id}`} className="mt-0.5 h-[15px] w-[15px] accent-foreground" />
            <span className="flex min-w-0 flex-col gap-px [overflow-wrap:anywhere]">
              <span><Escaped text={e.text} /></span>
              {e.same_as && <span data-testid={`memory-import-same-${e.id}`} className="text-[12px] text-muted-foreground">
                {t("discover.import_same", { stored: isolate(e.same_as) })}</span>}
            </span>
          </label>)}
        </span>
        {/* UNI1b, as the save-a-skill card: the count, never blocking; each run is a marker in its line. */}
        {hidden > 0 && <Notice tone="warn" testId="memory-import-hidden" className="mt-1.5">
          {t("discover.save_hidden", { count: hidden })}</Notice>}
      </Row>
      {(parts.length > 0 || card.too_many > 0) && <Row label={t("discover.import_left")} testId="memory-import-left">
        <span className="flex flex-col gap-[5px]">
          {parts.length > 0 && <span>{t("discover.import_leftCount", { count: card.left_out.length,
            parts: parts.join(t("discover.import_partJoin")) })}</span>}
          {parts.length > 0 && <button type="button" data-testid="memory-import-left-toggle" aria-expanded={open}
            onClick={() => setOpen(!open)} className="self-start text-[12px] text-primary hover:underline">
            {t(open ? "discover.import_hide" : "discover.import_show")}</button>}
          {open && parts.length > 0 && <span data-testid="memory-import-left-list"
            className="grid max-h-[160px] grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 overflow-auto rounded-lg border border-border bg-surface-raised px-2.5 py-2 text-[12px]">
            {card.left_out.map((l, i) => [
              <span key={`t${i}`} className="min-w-0 [overflow-wrap:anywhere]">
                {l.text === null ? <span className="text-muted-foreground">{t("discover.import_keyLine")}</span> : <Escaped text={l.text} />}
              </span>,
              <span key={`r${i}`} className="text-muted-foreground">{t(`discover.import_why_${l.reason}`)}</span>,
            ])}
          </span>}
          {card.too_many > 0 && <span data-testid="memory-import-too-many">{t("discover.import_tooMany", { count: card.too_many })}</span>}
        </span>
      </Row>}
      <Row label={t("discover.import_note")}>{t("discover.import_noteText")}</Row>
    </div>
  );
  return (
    <AskCard testId="memory-import-card" who={t("discover.import_who")} title={t("discover.import_title")} detail={detail}
      extra={<span className="text-[11px] text-subtle-foreground">{t("discover.import_footer")}</span>}
      expiresAt={expiresAt} queue={queue} allowDisabled={kept.length === 0}
      allowLabel={t("discover.import_allow", { count: kept.length })} declineLabel={t("discover.import_decline")}
      allowTestId="memory-import-allow" declineTestId="memory-import-decline"
      onAllow={() => onConfirm(callId, kept)} onDecline={() => onCancel(callId)} />
  );
}
