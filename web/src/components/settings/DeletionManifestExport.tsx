import { useEffect, useRef, useState } from "react";
import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { request } from "../../api/client";

export default function DeletionManifestExport() {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const alive = useRef(true);
  const pending = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
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
  </section>;
}
