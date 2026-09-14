import { useEffect, useRef, useState } from "react";
import { BookOpen, ChevronDown, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { companionApi, type ContextMemoryReview, type ContextReceiptRecord } from "../../api/companion";
import { buttonClass } from "./CompanionDialog";

type Props = { conversationId: string; taskId: string };
const reasons = new Set(["scope", "permission", "deleted", "inactive", "sensitive", "irrelevant", "budget"]);
const modes = new Set(["normal", "disabled", "temporary"]);

export default function MemoryEvidence(props: Props) {
  // A task switch must discard both pending responses and previously read text.
  return <Evidence key={JSON.stringify([props.conversationId, props.taskId])} {...props} />;
}

function Evidence({ conversationId, taskId }: Props) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<ContextReceiptRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [more, setMore] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [review, setReview] = useState<string | null>(null);
  const [detail, setDetail] = useState<ContextMemoryReview | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState(false);
  const generation = useRef(0);
  const reviewGeneration = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; generation.current++; reviewGeneration.current++; };
  }, []);

  function clearReview() {
    reviewGeneration.current++;
    setReview(null); setDetail(null); setReviewBusy(false); setReviewError(false);
  }
  useEffect(() => {
    if (!open) return;
    const current = ++generation.current;
    clearReview(); setRows([]); setBusy(true); setError(false); setMore(false);
    companionApi.contextReceipts(conversationId, taskId).then(next => {
      if (!mounted.current || generation.current !== current) return;
      setRows(next); setMore(next.length === 20);
    }).catch(() => { if (mounted.current && generation.current === current) setError(true); })
      .finally(() => { if (mounted.current && generation.current === current) setBusy(false); });
    return () => { generation.current++; reviewGeneration.current++; };
  }, [open, conversationId, taskId, refresh]);

  async function loadMore() {
    const cursor = rows.at(-1)?.id;
    if (!cursor || busy) return;
    const current = generation.current;
    setBusy(true); setError(false);
    try {
      const next = await companionApi.contextReceipts(conversationId, taskId, cursor);
      if (!mounted.current || generation.current !== current) return;
      setRows(previous => [...previous, ...next.filter(row => !previous.some(old => old.id === row.id))]);
      setMore(next.length === 20);
    } catch { if (mounted.current && generation.current === current) setError(true); }
    finally { if (mounted.current && generation.current === current) setBusy(false); }
  }
  async function inspect(receiptId: string, entryId: string) {
    const key = JSON.stringify([receiptId, entryId]);
    if (review === key && !reviewError) { clearReview(); return; }
    const current = ++reviewGeneration.current;
    setReview(key); setDetail(null); setReviewBusy(true); setReviewError(false);
    try {
      const next = await companionApi.contextMemory(conversationId, receiptId, entryId);
      if (mounted.current && reviewGeneration.current === current) setDetail(next);
    } catch { if (mounted.current && reviewGeneration.current === current) setReviewError(true); }
    finally { if (mounted.current && reviewGeneration.current === current) setReviewBusy(false); }
  }
  function toggle() {
    clearReview(); setRows([]); setError(false); setOpen(value => !value);
  }
  function date(value: string) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.valueOf()) ? t("memoryEvidence.unknown")
      : new Intl.DateTimeFormat(i18n.resolvedLanguage, { dateStyle: "short", timeStyle: "short" }).format(parsed);
  }

  return <section className="rounded-lg border border-border p-3">
    <button type="button" className="flex w-full items-center gap-2 text-left font-medium" aria-expanded={open} onClick={toggle}>
      <BookOpen size={15} /><span className="min-w-0 flex-1">{t("memoryEvidence.title")}</span><ChevronDown size={15} className={open ? "rotate-180" : ""} />
    </button>
    {open && <div className="mt-3 space-y-3 text-xs">
      <p className="leading-relaxed text-muted-foreground">{t("memoryEvidence.explanation")}</p>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => { clearReview(); setRefresh(value => value + 1); }}>
        <RefreshCw size={13} />{t("companion.refresh")}
      </button>
      {error && <p role="alert" className="text-destructive">{t("memoryEvidence.failure")}</p>}
      {!busy && !error && rows.length === 0 && <p>{t("memoryEvidence.unrecorded")}</p>}
      {rows.map(row => {
        const receipt: Partial<ContextReceiptRecord["receipt"]> = row.receipt ?? {};
        const refs = (Array.isArray(receipt.used) ? receipt.used : []).filter(ref =>
          ref && ref.kind === "memory" && typeof ref.id === "string" && ref.id.length > 0
          && Number.isInteger(ref.revision) && ref.revision > 0);
        const filters = Array.isArray(receipt.filter_reasons) ? receipt.filter_reasons : [];
        return <article key={row.id} className="space-y-2 rounded-lg bg-foreground/5 p-3" data-receipt-id={row.id}>
          <div className="flex flex-wrap items-center justify-between gap-2"><time dateTime={row.created_at}>{date(row.created_at)}</time>
            <span>{t(`memoryEvidence.${modes.has(receipt.memory_mode ?? "") ? receipt.memory_mode : "unknown"}`)}</span></div>
          <p className="text-muted-foreground">{t(receipt.cloud_use === "approved" ? "memoryEvidence.cloudApproved" : "memoryEvidence.noCloudRecord")}</p>
          <p>{t("memoryEvidence.tokens", { amount: typeof receipt.estimated_tokens === "number" && Number.isFinite(receipt.estimated_tokens) && receipt.estimated_tokens >= 0
            ? new Intl.NumberFormat(i18n.resolvedLanguage).format(receipt.estimated_tokens) : t("memoryEvidence.unknown") })}</p>
          {!!filters.length && <p className="leading-relaxed text-muted-foreground">{t("memoryEvidence.filters")}: {filters.map(reason =>
            t(`memoryEvidence.${reasons.has(reason) ? `filter_${reason}` : "unknown"}`)).join(" · ")}</p>}
          {refs.length === 0 && <p>{t("memoryEvidence.noneSelected")}</p>}
          {refs.map((ref, index) => {
            const selected = review === JSON.stringify([row.id, ref.id]);
            return <div key={`${ref.id}:${ref.revision}`} className="space-y-2">
              <button type="button" className={buttonClass} aria-expanded={selected} onClick={() => void inspect(row.id, ref.id)}>
                {t("memoryEvidence.entry", { number: index + 1, version: ref.revision })}
              </button>
              {selected && <div className="rounded-md border border-border bg-background p-3" aria-live="polite">
                {reviewBusy && <p role="status">{t("companion.loading")}</p>}
                {reviewError && <p role="alert" className="text-destructive">{t("memoryEvidence.failure")}</p>}
                {detail?.status === "deleted" && <p>{t("memoryEvidence.deletedEntry")}</p>}
                {detail?.status === "unavailable" && <p>{t("memoryEvidence.unavailableEntry")}</p>}
                {detail?.status === "available" && <>
                  {detail.current_version !== detail.recorded_version && <p className="mb-2 text-muted-foreground">{t("memoryEvidence.revised")}</p>}
                  <p className="whitespace-pre-wrap break-words">{detail.content}</p>
                </>}
              </div>}
            </div>;
          })}
        </article>;
      })}
      {busy && <p role="status">{t("companion.loading")}</p>}
      {more && <button type="button" className={buttonClass} disabled={busy} onClick={() => void loadMore()}>{t("companion.loadMore")}</button>}
    </div>}
  </section>;
}
