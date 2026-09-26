import { useEffect, useRef, useState } from "react";
import { Download, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { request } from "../../api/client";

export default function DeletionManifestExport() {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [record, setRecord] = useState<"current" | "ahead" | "attention" | null>(null);
  const alive = useRef(true);
  const pending = useRef(false);
  const checkPending = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function checkRecord() {
    if (checkPending.current) return;
    checkPending.current = true; setChecking(true); setRecord(null);
    try {
      const result = await request<{ status?: string; database_epoch?: number; saved_epoch?: number }>(
        "/memory/deletion-record-status", { cache: "no-store" });
      if (!alive.current) return;
      const current = result?.status === "current" && Number.isSafeInteger(result.database_epoch)
        && (result.database_epoch ?? -1) >= 0 && result.database_epoch === result.saved_epoch;
      setRecord(current ? "current" : result?.status === "ahead" ? "ahead" : "attention");
    } catch { if (alive.current) setRecord("attention"); }
    finally { checkPending.current = false; if (alive.current) setChecking(false); }
  }
  async function download() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setFailed(false);
    try {
      const manifest = await request<unknown>("/memory/deletion-manifest", { cache: "no-store" });
      if (!alive.current) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(manifest)], { type: "application/json" }));
      try {
        const anchor = document.createElement("a");
        anchor.href = url; anchor.download = "arslan-deletion-manifest.json";
        document.body.appendChild(anchor);
        try { anchor.click(); } finally { anchor.remove(); }
      } finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
    } catch { if (alive.current) setFailed(true); }
    finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  return <section className="space-y-2 border-t border-border/40 pt-5">
    <button type="button" disabled={busy} onClick={() => void download()}
      className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">
      <Download size={16} aria-hidden="true" />{t(busy ? "companion.loading" : "companion.exportDeletionManifest")}
    </button>
    <p className="text-xs text-muted-foreground">{t("companion.deletionManifestHint")}</p>
    {failed && <p role="alert" className="text-xs text-destructive">{t("companion.deletionManifestFailure")}</p>}
    <button type="button" disabled={checking} onClick={() => void checkRecord()}
      className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">
      <ShieldCheck size={16} aria-hidden="true" />{t(checking ? "companion.loading" : "companion.checkDeletionRecord")}
    </button>
    {record && <p role="status" className="text-xs text-muted-foreground">{t(record === "current"
      ? "companion.deletionRecordCurrent" : record === "ahead" ? "companion.deletionRecordAhead" : "companion.deletionRecordAttention")}</p>}
  </section>;
}
